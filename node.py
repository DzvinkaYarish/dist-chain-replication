import os
import sys
import threading
from concurrent import futures
from enum import Enum

import grpc
from dotenv import load_dotenv

from protos import control_panel_pb2, control_panel_pb2_grpc, node_pb2, node_pb2_grpc
from google.protobuf.empty_pb2 import Empty

load_dotenv()


class NodeState(Enum):
    INITIALIZED = 1
    PS_CREATED = 2
    CHAIN_CREATED = 3


class ProcessRole(Enum):
    NONE = 1
    HEAD = 2
    TAIL = 3
    DISABLED = 4


# In our case, a process will be a thread on a node
class Process(threading.Thread):
    def __init__(self, name):
        super().__init__()
        self.name = name
        self.db = {}
        # Stores a list of last 5 write operations (key, value) performed on the db.
        # Used to reconcile a restored head
        self.last_write_operations = []
        # Number of write operations performed on the db.
        # Used as numerical deviation during head restoration
        self.num_write_operations = 0
        self.control_panel_ip = None
        self.predecessor_ip = None
        self.successor_ip = None
        self.tail_ip = None
        self.role = None

    # In local_store_ps, the processes are first created and then during chain creation they are initialized
    def initialize(self, controlPanel, predecessor, successor, tail, role):
        self.control_panel_ip = controlPanel
        self.predecessor_ip = predecessor
        self.successor_ip = successor
        self.tail_ip = tail
        self.role = role

    def run(self):
        if self.control_panel_ip is None:
            print(f"Control Panel is None for {self.name}. Stopping...")
            return
        if self.role == ProcessRole.HEAD and (
                self.predecessor_ip is not None or self.successor_ip is None or self.tail_ip is None):
            print(f"Head process incorrectly initialized. Stopping...")
            return
        if self.role == ProcessRole.TAIL and (
                self.predecessor_ip is None or self.successor_ip is not None or self.tail_ip is not None):
            print(f"Tail process incorrectly initialized. Stopping...")
            return
        if self.role == ProcessRole.NONE and (
                self.predecessor_ip is None or self.successor_ip is None or self.tail_ip is None):
            print(f"Process incorrectly initialized. Stopping...")
            return
        if self.role == ProcessRole.DISABLED:
            print(f"Process {self.name} is disabled. Requests will not be processed")
        print(f"Process {self.name} started with role {self.role}")


# In our case, a node will be a process on a machine
class Node(node_pb2_grpc.NodeServicer):
    def __init__(self, name, ip, control_panel_ip):
        self.name = name
        self.ip = ip
        self.control_panel_ip = control_panel_ip
        self.state = NodeState.INITIALIZED
        self.processes = {}
        self.cmds = {
            'Local-store-ps': self.local_store_ps,
            'Create-chain': self.create_chain,
            'List-chain': self.list_chain,
            'Clear': self.clear,
            'Remove-head': self.remove_head,
            'Restore-head': self.restore_head,
        }

    def local_store_ps(self, n):
        n = int(n)
        if self.state != NodeState.INITIALIZED:
            print("Processes have already been created. "
                  "Please start a new program to create a different number of processes")
            return
        self.state = NodeState.PS_CREATED
        for i in range(n):
            name = f"{self.name}-ps{i}"
            self.processes[name] = Process(name)
            with grpc.insecure_channel(self.control_panel_ip) as channel:
                stub = control_panel_pb2_grpc.ControlPanelStub(channel)
                req = control_panel_pb2.NameIP(name=name, ip=self.ip)
                stub.AddProcess(req)

    def create_chain(self):
        if self.state == NodeState.INITIALIZED:
            print("Processes have not been created yet. "
                  "Please create processes with Local-store-ps <number of processes> command")
            return
        if self.state == NodeState.CHAIN_CREATED:
            print("Chain has already been created. "
                  "Please start a new program to create a new chain")
            return

        with grpc.insecure_channel(self.control_panel_ip) as channel:
            stub = control_panel_pb2_grpc.ControlPanelStub(channel)
            stub.CreateChain(Empty())

    def list_chain(self):
        if self.state != NodeState.CHAIN_CREATED:
            print("Chain has not been created yet. "
                  "Please create a chain with Create-chain command")
            return
        with grpc.insecure_channel(self.control_panel_ip) as channel:
            stub = control_panel_pb2_grpc.ControlPanelStub(channel)
            chain = stub.ListChain(Empty()).chain
        print(chain)

    def clear(self):
        with grpc.insecure_channel(self.control_panel_ip) as channel:
            stub = control_panel_pb2_grpc.ControlPanelStub(channel)
            stub.Clear(Empty())

    def remove_head(self):
        with grpc.insecure_channel(self.control_panel_ip) as channel:
            stub = control_panel_pb2_grpc.ControlPanelStub(channel)
            stub.RemoveHead(Empty())

    def restore_head(self):
        with grpc.insecure_channel(self.control_panel_ip) as channel:
            stub = control_panel_pb2_grpc.ControlPanelStub(channel)
            stub.RestoreHead(Empty())

    def Initialize(self, request, context):
        process = self.processes[request.processID]
        assert process is not None
        process.initialize(self.control_panel_ip, request.predecessorIP,
                           request.successorIP, request.tailIP, request.role)
        print(f"Process {request.processID} initialized")
        process.start()
        self.state = NodeState.CHAIN_CREATED  # even if one processes is initialized, consider the chain created
        return Empty()

    def Clear(self, request, context):
        print("Clearing...")
        self.state = NodeState.INITIALIZED
        self.processes = {}
        return Empty()

    def SetPredecessorIP(self, request, context):
        process = self.processes[request.processID]
        assert process is not None
        process.predecessor_ip = request.ip
        return Empty()

    def SetRole(self, request, context):
        process = self.processes[request.processID]
        assert process is not None
        new_role = ProcessRole(request.role)
        process.role = new_role
        return Empty()

    def GetNumericalDeviation(self, request, context):
        process = self.processes[request.processID]
        assert process is not None
        return node_pb2.NumericalDeviation(deviation=process.num_write_operations)

    def Reconcile(self, request, context):
        process = self.processes[request.sourceProcessID]
        assert process is not None
        max_deviation = len(process.last_write_operations)
        with grpc.insecure_channel(request.targetIP) as channel:
            stub = node_pb2_grpc.NodeStub(channel)
            deviation = stub.GetNumericalDeviation(
                node_pb2.NumericalDeviationRequest(processID=request.targetProcessID)
            ).deviation
            diff = process.num_write_operations - deviation
            assert 0 <= diff <= max_deviation
            for i in range(max_deviation - diff, max_deviation):
                key, value = process.last_write_operations[i]
                stub.RawWrite(node_pb2.RawWriteRequest(processID=request.targetProcessID, key=key, value=value))
        return Empty()

    def RawWrite(self, request, context):
        process = self.processes[request.processID]
        assert process is not None
        process.db[request.key] = request.value
        return Empty()

    def handle_input(self, inp):
        inp = inp.strip().split(' ')
        try:
            self.cmds[inp[0]](*inp[1:])
        except KeyError:
            print('Invalid command.')
        except TypeError:
            print('Invalid arguments to the command.')

    @staticmethod
    def print_help():
        print('''
Commands:
    Local-store-ps <number of processes>
    Create-chain
    List-chain
    Clear
    Remove-head
    Restore-head
    ''')


if __name__ == '__main__':
    name = f"Node{sys.argv[1]}"
    ip = os.environ[f"{name}_IP"]
    port = ip.split(":")[-1]
    print(f"Starting node {name} with ip {ip}")
    n = Node(name, ip, os.environ["CONTROL_PANEL_IP"])
    n.print_help()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    node_pb2_grpc.add_NodeServicer_to_server(n, server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()

    while True:
        try:
            print("> ", end="")
            inp = input()
            if not inp.strip():
                continue
            n.handle_input(inp)
        except KeyboardInterrupt:
            server.stop(0)
            exit()
    server.stop(0)

import os
import sys
import threading
from enum import Enum

import grpc
from dotenv import load_dotenv

from protos import control_panel_pb2, control_panel_pb2_grpc

load_dotenv()


class NodeState(Enum):
    INITIALIZED = 1,
    PS_CREATED = 2,
    CHAIN_CREATED = 3,


class ProcessRole(Enum):
    NONE = 1,
    HEAD = 2,
    TAIL = 3,


# In our case, a process will be a thread on a node
class Process(threading.Thread):
    def __init__(self, name):
        super().__init__()
        self.name = name
        self.db = {}
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
        print(f"Process {self.name} started with role {self.role}")


# In our case, a node will be a process on a machine
class Node:
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
        self.state = NodeState.CHAIN_CREATED

        with grpc.insecure_channel(self.control_panel_ip) as channel:
            stub = control_panel_pb2_grpc.ControlPanelStub(channel)
            req = control_panel_pb2.Empty()
            chain = stub.CreateChain(req).chain

        for i in range(len(chain)):
            name = chain[i].name
            if self.processes[name] is None:
                continue
            predecessor_ip = chain[i - 1].ip if i > 0 else None
            successor_ip = chain[i + 1].ip if i < len(chain) - 1 else None
            tail_ip = chain[-1].ip if i != len(chain) - 1 else None
            role = ProcessRole.HEAD if i == 0 else ProcessRole.TAIL if i == len(chain) - 1 else ProcessRole.NONE
            self.processes[name].initialize(self.control_panel_ip, predecessor_ip, successor_ip, tail_ip, role)
        for p in self.processes.values():
            p.start()

    def list_chain(self):
        if self.state != NodeState.CHAIN_CREATED:
            print("Chain has not been created yet. "
                  "Please create a chain with Create-chain command")
            return
        with grpc.insecure_channel(self.control_panel_ip) as channel:
            stub = control_panel_pb2_grpc.ControlPanelStub(channel)
            req = control_panel_pb2.Empty()
            chain = stub.ListChain(req).chain
        print(chain)

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
    ''')


if __name__ == '__main__':
    name = f"Node{sys.argv[1]}"
    ip = os.environ[f"{name}_IP"]
    n = Node(name, ip, os.environ["CONTROL_PANEL_IP"])
    n.print_help()
    while True:
        try:
            print("> ", end="")
            inp = input()
            if not inp.strip():
                continue
            n.handle_input(inp)
        except KeyboardInterrupt:
            exit()

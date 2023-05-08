import os
import sys
from concurrent import futures
from enum import Enum
import time

import grpc
from dotenv import load_dotenv

from protos import control_panel_pb2, control_panel_pb2_grpc, process_pb2, process_pb2_grpc
from google.protobuf.empty_pb2 import Empty

load_dotenv()


class ProcessState(Enum):
    INITIALIZED = 1
    INACTIVE = 2
    CHAIN_CREATED = 3


class ProcessRole(Enum):
    NONE = 1
    HEAD = 2
    TAIL = 3
    DISABLED = 4


# In our case, a process will be a thread on a node
class Process(process_pb2_grpc.ProcessServicer):
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
        self.ip = None
        self.control_panel_ip = None
        self.predecessor_ip = None
        self.successor_ip = None
        self.tail_ip = None
        self.head_ip = None
        self.role = None
        self.process_server = None
        self.state = ProcessState.INITIALIZED

    # In local_store_ps, the processes are first created and then during chain creation they are initialized
    def initialize(self, controlPanel, predecessor, successor, head, tail, role):
        self.control_panel_ip = controlPanel
        self.predecessor_ip = predecessor
        self.successor_ip = successor
        self.tail_ip = tail
        self.head_ip = head
        self.role = ProcessRole(role)
    
    def Initialize(self, request, context):
        self.initialize(self.control_panel_ip, request.predecessorIP,
                           request.successorIP, request.headIP, request.tailIP, request.role)
        print(f"Process {request.processID} initialized")
        self.state = ProcessState.CHAIN_CREATED  # even if one processes is initialized, consider the chain created
        return Empty()
    
    def Clear(self, request, context):
        print("Clearing...")
        self.state = ProcessState.INACTIVE
        self.process_server.stop(0)

        return Empty()

    def Write(self, request, context):
        print(f"Write is in role {self.role} in {self.name}")
        time.sleep(request.timeout)
        if self.role == ProcessRole.TAIL:
            self.db[request.key] = (request.value, 'clean')
        else:
            with grpc.insecure_channel(self.successor_ip) as channel:
                stub = process_pb2_grpc.ProcessStub(channel)
                self.db[request.key] = (request.value, 'dirty')
                stub.Write(request)
                self.db[request.key] = (request.value, 'clean')
        return Empty()

    def Read(self, request, context):
        if request.key in self.db:
            if self.db[request.key][1] == 'clean':
                return process_pb2.ReadResponse(value=float(self.db[request.key][0]), success=True)
            else:
                with grpc.insecure_channel(self.tail_ip) as channel:
                    stub = process_pb2_grpc.ProcessStub(channel)
                    return stub.Read(request)
        else:
            return process_pb2.ReadResponse(value=float(0.1), success=False)

    def ListBooks(self, request, context):
        book_lists = dict()
        if self.role == ProcessRole.TAIL:
            for key, value in self.db.items():
                book_lists[key] = value[0]
        else:
            with grpc.insecure_channel(self.tail_ip) as channel:
                stub = process_pb2_grpc.ProcessStub(channel)
                for key, value in self.db.items():
                    if value[1] == 'clean':
                        book_lists[key] = value[0]
                    else:
                        resp = stub.Read(process_pb2.ReadRequest(key=key))
                        if resp.value is not None:
                            book_lists[key] = resp.value
        return process_pb2.BookList(books=book_lists)

    def DataStatus(self, request, context):
        status = dict()
        for key, value in self.db.items():
            status[key] = value[1]
        return process_pb2.StatusResponse(status=status)

    def SetPredecessorIP(self, request, context):
        self.predecessor_ip = request.ip
        return Empty()

    def SetRole(self, request, context):
        new_role = ProcessRole(request.role)
        self.role = new_role
        return Empty()

    def GetNumericalDeviation(self, request, context):
        return process_pb2.NumericalDeviation(deviation=self.num_write_operations)

    def Reconcile(self, request, context):
        max_deviation = len(self.last_write_operations)
        with grpc.insecure_channel(request.targetIP) as channel:
            stub = process_pb2_grpc.ProcessStub(channel)
            deviation = stub.GetNumericalDeviation(
                process_pb2.NumericalDeviationRequest(processID=request.targetProcessID)
            ).deviation
            diff = self.num_write_operations - deviation
            assert 0 <= diff <= max_deviation
            for i in range(max_deviation - diff, max_deviation):
                key, value = self.last_write_operations[i]
                stub.RawWrite(process_pb2.RawWriteRequest(processID=request.targetProcessID, key=key, value=value))
        return Empty()

    def RawWrite(self, request, context):
        self.db[request.key] = request.value
        return Empty()
    
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
class Node():
    def __init__(self, name, ip, control_panel_ip):
        self.name = name
        self.ip = ip
        self.control_panel_ip = control_panel_ip
        self.processes = {}
        self.cmds = {
            'Local-store-ps': self.local_store_ps,
            'Create-chain': self.create_chain,
            'List-chain': self.list_chain,
            'Clear': self.clear,
            'Remove-head': self.remove_head,
            'Restore-head': self.restore_head,
            'Write-operation': self.write_operation,
            'Read-operation': self.read_operation,
            'List-books': self.list_books,
            'Data-status': self.data_status
        }
        # self.cmds = {'l': self.local_store_ps,
        #              'w': self.write_operation,
        #              'r': self.read_operation,
        #              'c': self.create_chain,}

    def local_store_ps(self, n):
        n = int(n)
        if len(self.processes) != 0 and self.processes[next(iter(self.processes))].state != ProcessState.INACTIVE:
            print("Processes have already been created. "
                  "Please start a new program to create a different number of processes")
            return
        self.processes = {}
        for i in range(n):
            name = f"{self.name}-ps{i}"
            process = Process(name)
            process.ip = self.ip.split(":")[0] + f":{int(self.ip.split(':')[-1]) + i + 1}"

            server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
            process_pb2_grpc.add_ProcessServicer_to_server(process, server)
            server.add_insecure_port(f"[::]:{process.ip.split(':')[-1]}")
            server.start()
            process.process_server = server

            with grpc.insecure_channel(self.control_panel_ip) as channel:
                stub = control_panel_pb2_grpc.ControlPanelStub(channel)
                req = control_panel_pb2.NameIP(name=name, ip=process.ip)
                stub.AddProcess(req)

            self.processes[name] = process

    def create_chain(self):
        if len(self.processes) == 0 or self.processes[next(iter(self.processes))].state == ProcessState.INACTIVE:
            print("Processes have not been created yet. "
                  "Please create processes with Local-store-ps <number of processes> command")
            return
        if self.processes[next(iter(self.processes))].state == ProcessState.CHAIN_CREATED:
            print("Chain has already been created. "
                  "Please start a new program to create a new chain")
            return

        with grpc.insecure_channel(self.control_panel_ip) as channel:
            stub = control_panel_pb2_grpc.ControlPanelStub(channel)
            stub.CreateChain(Empty())

    def list_chain(self):
        if self.processes[next(iter(self.processes))].state != ProcessState.CHAIN_CREATED:
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

    def write_operation(self, bp_pair, timeout):
        # NO SPACES IN INPUT
        cleaned_bp_pair = bp_pair.strip()
        if cleaned_bp_pair[0] != '<' and cleaned_bp_pair[-1] != '>':
            print('Invalid input')
            return
        cleaned_bp_pair = cleaned_bp_pair.strip('<>')
        pair_vals = cleaned_bp_pair.split(',')
        if len(pair_vals) != 2:
            print('Invalid input')
            return
        bname, price = pair_vals
        bname = bname.strip('""')
        try:
            price = float(price)
            timeout = int(timeout)
        except Exception as e:
            print(e)
            print("Invalid input")
            return
        with grpc.insecure_channel(self.processes[next(iter(self.processes))].head_ip) as channel:
            stub = process_pb2_grpc.ProcessStub(channel)

            stub.Write(process_pb2.WriteRequest(key=bname, value=price, timeout=timeout))

    def read_operation(self, bname):
        # NO SPACES IN INPUT
        bname = bname.strip('" ')
        ip = self.processes[next(iter(self.processes))].ip
        with grpc.insecure_channel(ip) as channel:
            stub = process_pb2_grpc.ProcessStub(channel)
            response = stub.Read(process_pb2.ReadRequest(key=bname))
            if response.success:
                print(f"Book name: {bname}, price: {response.value}")
            else:
                print("Book not found")

    def list_books(self):
        with grpc.insecure_channel(self.processes[next(iter(self.processes))].ip) as channel:
            stub = process_pb2_grpc.ProcessStub(channel)
            response = stub.ListBooks(Empty())
            print(response.books)

    def data_status(self, pname):
        # NO SPACES IN INPUT
        pname = pname.strip()
        if pname not in self.processes.keys():
            print("Invalid input")
            return
        else:
            with grpc.insecure_channel(self.processes[pname].ip) as channel:
                stub = process_pb2_grpc.ProcessStub(channel)
                response = stub.DataStatus(Empty())
                print(response.status)

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
    Write-operation <book name, price> <timeout>
    Read-operation <book name>
    Data-status
    List-books
    ''')


if __name__ == '__main__':
    name = f"Node{sys.argv[1]}"
    ip = os.environ[f"{name}_IP"]
    port = ip.split(":")[-1]
    print(f"Starting node {name} with ip {ip}")
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
            for process in n.processes.values():
                if process.process_server:
                    process.process_server.stop(0)
            exit()
    for process in n.processes.values():
        process.process_server.stop(0)

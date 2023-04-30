import threading
from enum import Enum


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
        self.controlPanel = None
        self.predecessor = None
        self.successor = None
        self.tail = None
        self.role = None

    # In local_store_ps, the processes are first created and then during chain creation they are initialized
    def initialize(self, controlPanel, predecessor, successor, tail, role):
        self.controlPanel = controlPanel
        self.predecessor = predecessor
        self.successor = successor
        self.tail = tail
        self.role = role

    def run(self):
        if self.controlPanel is None:
            print(f"Control Panel is None for {self.name}. Stopping...")
            return
        if self.role == ProcessRole.HEAD and (
                self.predecessor is not None or self.successor is None or self.tail is None):
            print(f"Head process incorrectly initialized. Stopping...")
            return
        if self.role == ProcessRole.TAIL and (
                self.predecessor is None or self.successor is not None or self.tail is not None):
            print(f"Tail process incorrectly initialized. Stopping...")
            return
        if self.role == ProcessRole.NONE and (
                self.predecessor is None or self.successor is None or self.tail is None):
            print(f"Process incorrectly initialized. Stopping...")
            return


# In our case, a node will be a process on a machine
class Node:
    def __init__(self, name, controlPanel):
        self.name = name
        self.controlPanel = controlPanel
        self.state = NodeState.INITIALIZED
        self.processes = {}
        self.cmds = {
            'Local-store-ps': self.local_store_ps,
            'Create-chain': self.create_chain,
            'List-chain': self.list_chain,
        }

    def local_store_ps(self, n: int):
        if self.state != NodeState.INITIALIZED:
            print("Processes have already been created. "
                  "Please start a new program to create a different number of processes")
            return
        self.state = NodeState.PS_CREATED
        for i in range(n):
            name = f"{self.name}-ps{i}"
            self.processes[name] = Process(name)
            self.controlPanel.add_process(name)

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
        chain = self.controlPanel.create_chain()
        for i in range(len(chain)):
            name = chain[i]
            if self.processes[name] is None:
                continue
            predecessor = chain[i - 1] if i > 0 else None
            successor = chain[i + 1] if i < len(chain) - 1 else None
            tail = chain[-1]
            role = ProcessRole.HEAD if i == 0 else ProcessRole.TAIL if i == len(chain) - 1 else ProcessRole.NONE
            self.processes[name].initialize(self.controlPanel, predecessor, successor, tail, role)
        for p in self.processes.values():
            p.start()

    def list_chain(self):
        if self.state != NodeState.CHAIN_CREATED:
            print("Chain has not been created yet. "
                  "Please create a chain with Create-chain command")
            return
        print(self.controlPanel.list_chain())

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


# TODO ips and integrate control panel GRPC server
if __name__ == '__main__':
    n = Node("Node1")
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

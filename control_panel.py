import random


def ControlPanel():
    def __init__(self):
        self.processes = []

    def add_process(self, name):
        self.processes.append(name)

    # Returns a list of processes in the chain
    # The first element is the head
    # The last element is the tail
    def create_chain(self):
        if len(self.processes) < 2:
            print("There should be at least 2 processes to create a chain")
            return
        random.shuffle(self.processes)
        return self.processes

    def list_chain(self):
        string = ""
        string += f"{self.processes[0]} (Head) -> "
        for p in self.processes[1:-1]:
            string += f"{p} -> "
        string += f"{self.processes[-1]} (Tail)"
        return string

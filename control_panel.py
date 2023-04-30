import os
import random
from concurrent import futures
from enum import Enum

import grpc
from dotenv import load_dotenv

from protos import control_panel_pb2, control_panel_pb2_grpc, node_pb2, node_pb2_grpc
from google.protobuf.empty_pb2 import Empty

load_dotenv()


class ControlPanelState(Enum):
    INITIALIZED = 1,
    CHAIN_CREATED = 2,


class ControlPanel(control_panel_pb2_grpc.ControlPanelServicer):
    def __init__(self):
        self.state = ControlPanelState.INITIALIZED
        self.processes = []  # list of control_panel_pb2.NameIP(name=name, ip=ip)

    def AddProcess(self, request, context):
        if self.state != ControlPanelState.INITIALIZED:
            print("Processes can only be added in the INITIALIZED state")
            return Empty()
        self.processes.append(control_panel_pb2.NameIP(name=request.name, ip=request.ip))
        print(f"Added process {request.name} with ip {request.ip}")
        return Empty()

    # Returns a list of processes in the chain
    # The first element is the head
    # The last element is the tail
    def CreateChain(self, request, context):
        if self.state == ControlPanelState.INITIALIZED:
            if len(self.processes) < 2:
                print("There should be at least 2 processes to create a chain")
                return control_panel_pb2.CreateChainResponse()
            random.shuffle(self.processes)
            # Here you can perform some extra checks
            # (e.g. reshuffle if subsequent chain elements are on the same node)
            self.state = ControlPanelState.CHAIN_CREATED
            print("Chain created!")
        else:
            print("Chain has already been created")
        chain = self.get_chain()
        print(f"Chain: {chain}")
        return control_panel_pb2.CreateChainResponse(chain=self.processes)

    def ListChain(self, request, context):
        if self.state != ControlPanelState.CHAIN_CREATED:
            print("Chain has not been created yet")
            return control_panel_pb2.ListChainResponse()
        chain = self.get_chain()
        print(f"Chain: {chain}")
        return control_panel_pb2.ListChainResponse(chain=chain)

    def Clear(self, request, context):
        nodes = set(map(lambda p: p.ip, self.processes))
        for node_ip in nodes:
            print(f"Clearing node {node_ip}")
            with grpc.insecure_channel(node_ip) as channel:
                stub = node_pb2_grpc.NodeStub(channel)
                stub.Clear(Empty())
        self.state = ControlPanelState.INITIALIZED
        self.processes = []
        print("Chain has been cleared")
        return Empty()

    def get_chain(self):
        string = ""
        string += f"{self.processes[0].name} (Head) -> "
        for p in self.processes[1:-1]:
            string += f"{p.name} -> "
        string += f"{self.processes[-1].name} (Tail)"
        return string


if __name__ == '__main__':
    port = os.environ["CONTROL_PANEL_IP"].split(":")[-1]

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    control_panel_pb2_grpc.add_ControlPanelServicer_to_server(ControlPanel(), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print(f"Control panel running on port {port}...")
    server.wait_for_termination()

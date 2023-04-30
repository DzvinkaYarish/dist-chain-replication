import os
import random
from concurrent import futures

import grpc
from dotenv import load_dotenv

from protos import control_panel_pb2, control_panel_pb2_grpc

load_dotenv()


class ControlPanel(control_panel_pb2_grpc.ControlPanelServicer):
    def __init__(self):
        self.processes = []  # list of control_panel_pb2.NameIP(name=name, ip=ip)

    def AddProcess(self, request, context):
        self.processes.append(control_panel_pb2.NameIP(name=request.name, ip=request.ip))
        print(f"Added process {request.name} with ip {request.ip}")
        return control_panel_pb2.Empty()

    # Returns a list of processes in the chain
    # The first element is the head
    # The last element is the tail
    def CreateChain(self, request, context):
        if len(self.processes) < 2:
            print("There should be at least 2 processes to create a chain")
            return control_panel_pb2.CreateChainResponse()
        random.shuffle(self.processes)
        chain = self.get_chain()
        print(f"Chain: {chain}")
        return control_panel_pb2.CreateChainResponse(chain=self.processes)

    def ListChain(self, request, context):
        chain = self.get_chain()
        print(f"Chain: {chain}")
        return control_panel_pb2.ListChainResponse(chain=chain)

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

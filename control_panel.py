import os
import random
from concurrent import futures
from enum import Enum
from node import ProcessRole

import grpc
from dotenv import load_dotenv

from protos import control_panel_pb2, control_panel_pb2_grpc, process_pb2, process_pb2_grpc
from google.protobuf.empty_pb2 import Empty

load_dotenv()


class ControlPanelState(Enum):
    INITIALIZED = 1,
    CHAIN_CREATED = 2,


class ControlPanel(control_panel_pb2_grpc.ControlPanelServicer):
    def __init__(self):
        self.state = ControlPanelState.INITIALIZED
        self.processes = []  # list of control_panel_pb2.NameIP(name=name, ip=ip)
        self.removed_heads = []  # like processes but used while removing and restoring heads

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
        print(f"Chain: {self.get_chain()}")

        for i in range(len(self.processes)):
            name, ip = self.processes[i].name, self.processes[i].ip
            predecessor_ip = self.processes[i - 1].ip if i > 0 else None
            successor_ip = self.processes[i + 1].ip if i < len(self.processes) - 1 else None
            tail_ip = self.processes[-1].ip if i != len(self.processes) - 1 else None
            head_ip = self.processes[0].ip if i != 0 else None

            role = ProcessRole.HEAD if i == 0 else ProcessRole.TAIL if i == len(self.processes) - 1 else ProcessRole.NONE

            with grpc.insecure_channel(ip) as channel:
                print('Creating process servicers')
                stub = process_pb2_grpc.ProcessStub(channel)
                res = stub.Initialize(process_pb2.InitializeRequest(
                    processID=name,
                    predecessorIP=predecessor_ip,
                    successorIP=successor_ip,
                    tailIP=tail_ip,
                    headIP=head_ip,
                    role=role.value,
                ))
                print(res)

        return control_panel_pb2.CreateChainResponse(chain=self.processes)

    def ListChain(self, request, context):
        if self.state != ControlPanelState.CHAIN_CREATED:
            print("Chain has not been created yet")
            return control_panel_pb2.ListChainResponse()
        chain = self.get_chain()
        print(f"Chain: {chain}")
        return control_panel_pb2.ListChainResponse(chain=chain)

    def Clear(self, request, context):
        processes_ips = set(map(lambda p: p.ip, self.removed_heads + self.processes))
        for ip in processes_ips:
            print(f"Clearing process {ip}")
            with grpc.insecure_channel(ip) as channel:
                stub = process_pb2_grpc.ProcessStub(channel)
                stub.Clear(Empty())
        self.state = ControlPanelState.INITIALIZED
        self.processes = []
        self.removed_heads = []
        print("Chain has been cleared")
        return Empty()

    def GetHead(self, request, context):
        if self.state != ControlPanelState.CHAIN_CREATED:
            print("Chain has not been created yet")
            return control_panel_pb2.GetHeadResponse()
        return control_panel_pb2.GetHeadResponse(head=self.processes[0])

    def RemoveHead(self, request, context):
        print("Removing head...")
        if self.state != ControlPanelState.CHAIN_CREATED:
            print("Chain has not been created yet")
            return Empty()
        if len(self.processes) == 1:
            print("There is only one process in the chain")
            return Empty()
        # Set the new head
        self.removed_heads.append(self.processes.pop(0))
        # Disable the previous head
        previous_head_name, previous_head_ip = self.removed_heads[-1].name, self.removed_heads[-1].ip
        with grpc.insecure_channel(previous_head_ip) as channel:
            stub = process_pb2_grpc.NodeStub(channel)
            stub.SetRole(process_pb2.NodeRole(
                processID=previous_head_name,
                role=ProcessRole.DISABLED.value
            ))
        new_head_name, new_head_ip = self.processes[0].name, self.processes[0].ip
        with grpc.insecure_channel(new_head_ip) as channel:
            stub = process_pb2_grpc.NodeStub(channel)
            # Set the next node as a new head
            stub.SetRole(process_pb2.NodeRole(
                processID=new_head_name,
                role=ProcessRole.HEAD.value
            ))
            # Set the new head predecessor's to None
            stub.SetPredecessorIP(process_pb2.SetPredecessorIPRequest(processID=new_head_name))
        print(f"Head {previous_head_name} ({previous_head_ip}) has been removed")
        return Empty()

    def RestoreHead(self, request, context):
        print("Restoring head...")
        if self.state != ControlPanelState.CHAIN_CREATED:
            print("Chain has not been created yet")
            return Empty()
        if len(self.removed_heads) == 0:
            print("There are no heads to restore")
            return Empty()
        if ControlPanel.compare_numerical_deviation(self.removed_heads[-1], self.processes[0]):
            node = self.removed_heads.pop()
            print(f"Numerical deviation is too high. Node {node.name} ({node.ip}) has been permanently removed.")
            return Empty()
        print(f"Numerical deviation is acceptable. Restoring head...")
        # Set the removed head as the new head
        self.processes.insert(0, self.removed_heads.pop())
        # Enable the new head
        new_head_name, new_head_ip = self.processes[0].name, self.processes[0].ip
        with grpc.insecure_channel(new_head_ip) as channel:
            stub = process_pb2_grpc.NodeStub(channel)
            stub.SetRole(process_pb2.NodeRole(
                processID=new_head_name,
                role=ProcessRole.HEAD.value
            ))
        print("here2")
        old_head_name, old_head_ip = self.processes[1].name, self.processes[1].ip
        with grpc.insecure_channel(old_head_ip) as channel:
            stub = process_pb2_grpc.NodeStub(channel)
            # Set the previous head role
            stub.SetRole(process_pb2.NodeRole(
                processID=old_head_name,
                role=ProcessRole.NONE.value
            ))
            # change the current node prev to None
            stub.SetPredecessorIP(process_pb2.SetPredecessorIPRequest(
                processID=old_head_name,
                ip=new_head_ip
            ))
            # reconciling
            stub.Reconcile(process_pb2.ReconcileRequest(
                sourceProcessID=old_head_name,
                targetProcessID=new_head_name,
                targetIP=new_head_ip
            ))
        print(f"Process {self.processes[0].name} ({self.processes[0].ip}) has been restored as the head. "
              f"Reconciled successfully.")
        return Empty()

    def get_chain(self):
        string = ""
        string += f"{self.processes[0].name} (Head)"
        for p in self.processes[1:-1]:
            string += f" -> {p.name}"
        string += f" -> {self.processes[-1].name} (Tail)"
        return string

    # Returns True if the numerical deviation between the two nodes is greater than 5
    @staticmethod
    def compare_numerical_deviation(node1, node2):
        with grpc.insecure_channel(node1.ip) as channel:
            stub = process_pb2_grpc.NodeStub(channel)
            node1_deviation = stub.GetNumericalDeviation(
                process_pb2.NumericalDeviationRequest(processID=node1.name)
            ).deviation
        with grpc.insecure_channel(node2.ip) as channel:
            stub = process_pb2_grpc.NodeStub(channel)
            node2_deviation = stub.GetNumericalDeviation(
                process_pb2.NumericalDeviationRequest(processID=node2.name)
            ).deviation
        return abs(node1_deviation - node2_deviation) > 5


if __name__ == '__main__':
    port = os.environ["CONTROL_PANEL_IP"].split(":")[-1]

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    control_panel_pb2_grpc.add_ControlPanelServicer_to_server(ControlPanel(), server)
    server.add_insecure_port(f"[::]:{port}")
    try:
        server.start()
        print(f"Control panel running on port {port}...")
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(0)

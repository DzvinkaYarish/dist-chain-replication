python -m grpc_tools.protoc -I . --python_out=. --grpc_python_out=. ./protos/control_panel.proto
python -m grpc_tools.protoc -I . --python_out=. --grpc_python_out=. ./protos/node.proto

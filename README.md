# Book Store with Chain Replication project for Distributed Systems course

## Dzvenymyra-Marta Yarish, Nikita Fordui, Anton Zaliznyi

## How to run

### Setup virtual environment

Create a virtual environment

```bash
python -m venv venv
```

Activate the virtual environment

For Windows:

```bash
"venv/Scripts/activate.bat"
```

For Linux:

```bash
venv/Scripts/activate
```

### Install the dependencies

```bash
python -m pip install -r requirements.txt
```

### Generate proto files

```bash
python -m grpc_tools.protoc -I . --python_out=. --grpc_python_out=. ./protos/control_panel.proto
python -m grpc_tools.protoc -I . --python_out=. --grpc_python_out=. ./protos/process.proto
```

Alternatively, you can also execute `./generate_protos.sh` or `./generate_protos.bat` 
script in the root directory.

### Run the processes 

1. Edit the configuration file `.env`

2. Run the control panel

```bash
python control_panel.py
```

3. Run the nodes

```bash
python node.py <node_id>
```

HINT: In IDEs like PyCharm you  can set up command line arguments and allow parallel runs

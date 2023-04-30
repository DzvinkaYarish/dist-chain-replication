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
```

Alternatively, you can also execute `./generate_protos.sh` or `./generate_protos.bat` 
script in the root directory.

### Run the processes 

TODO
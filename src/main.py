import asyncio
from viam.module.module import Module
try:
    from models.gate_opener import GateOpener
except ModuleNotFoundError:
    # when running as local module with run.sh
    from .models.gate_opener import GateOpener


if __name__ == '__main__':
    asyncio.run(Module.run_from_registry())

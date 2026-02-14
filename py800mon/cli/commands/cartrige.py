import sys

from ...rpc import Command
from ..common import async_to_sync, rpc_client


def register(subparsers):
    cart = subparsers.add_parser("cart", help="Cartridge commands.")
    cart_sub = cart.add_subparsers(dest="cart_cmd", metavar="subcmd")

    status = cart_sub.add_parser("status", help="Show cartridge state.")
    status.set_defaults(func=cmd_status)

    remove = cart_sub.add_parser("remove", help="Remove cartridge.")
    remove.set_defaults(func=cmd_remove)

    cart.set_defaults(func=cmd_status)


def cmd_status(args):
    state = async_to_sync(rpc_client(args.socket).cartrige_state())
    sys.stdout.write(f"autoreboot:    {state.autoreboot}\n")
    sys.stdout.write(f"main_present:  {state.main.present}\n")
    sys.stdout.write(f"main_type:     {state.main.cart_type}\n")
    sys.stdout.write(f"main_state:    {state.main.state:08X}\n")
    sys.stdout.write(f"main_size_kb:  {state.main.size_kb}\n")
    sys.stdout.write(f"main_raw:      {state.main.raw}\n")
    sys.stdout.write(f"piggy_present: {state.piggy.present}\n")
    sys.stdout.write(f"piggy_type:    {state.piggy.cart_type}\n")
    sys.stdout.write(f"piggy_state:   {state.piggy.state:08X}\n")
    sys.stdout.write(f"piggy_size_kb: {state.piggy.size_kb}\n")
    sys.stdout.write(f"piggy_raw:     {state.piggy.raw}\n")
    return 0


def cmd_remove(args):
    async_to_sync(rpc_client(args.socket).call(Command.REMOVECARTRIGE))
    return 0

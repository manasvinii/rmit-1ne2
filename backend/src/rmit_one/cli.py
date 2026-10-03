import argparse
from . import greet

def main():
    parser = argparse.ArgumentParser(prog="awesome-project", description="Awesome Project CLI")
    parser.add_argument("--name", "-n", default="world", help="Name to greet")
    args = parser.parse_args()
    print(greet(args.name))

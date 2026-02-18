from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass


class Exit(SystemExit):
    pass


@dataclass
class _OptionValue:
    default: object


def Option(default=None, *_, **__):
    return _OptionValue(default)


def prompt(text: str, default: str = "", show_default: bool = True) -> str:
    suffix = f" [{default}]" if show_default and default != "" else ""
    raw = input(f"{text}{suffix}: ").strip()
    return raw or default


class Typer:
    def __init__(self, help: str | None = None):
        self.help = help
        self._commands = {}

    def command(self, name: str | None = None):
        def deco(fn):
            self._commands[name or fn.__name__.replace('_', '-')] = fn
            return fn
        return deco

    def __call__(self):
        argv = sys.argv[1:]
        if not argv or argv[0] in {"-h", "--help"}:
            print(self.help or "")
            print("Commands:", ", ".join(sorted(self._commands.keys())))
            return
        cmd = argv[0]
        fn = self._commands.get(cmd)
        if not fn:
            raise Exit(f"Unknown command: {cmd}")

        sig = inspect.signature(fn)
        kwargs = {}
        args_iter = iter(argv[1:])
        for token in args_iter:
            if token.startswith("--"):
                key = token[2:].replace('-', '_')
                param = sig.parameters.get(key)
                if param is None:
                    continue
                if param.annotation is bool or isinstance(param.default, _OptionValue) and isinstance(param.default.default, bool):
                    kwargs[key] = True
                else:
                    kwargs[key] = next(args_iter)

        for k, p in sig.parameters.items():
            if k in kwargs:
                continue
            d = p.default
            if isinstance(d, _OptionValue):
                kwargs[k] = d.default
            elif d is not inspect._empty:
                kwargs[k] = d
        fn(**kwargs)

#!/usr/bin/env python3
# Copyright 2018-2026 the Deno authors. MIT license.
"""Read the literal vars/deps tables in a pinned Chromium DEPS file as data."""

import ast
from pathlib import Path


def read_deps(path: Path) -> dict:
    variables = {}

    def value(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.List, ast.Tuple)):
            return [value(item) for item in node.elts]
        if isinstance(node, ast.Dict):
            return {value(key): value(item) for key, item in zip(node.keys, node.values)}
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return value(node.left) + value(node.right)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if len(node.args) == 1 and not node.keywords:
                argument = value(node.args[0])
                if node.func.id == "Var":
                    return variables[argument]
                if node.func.id == "Str" and isinstance(argument, str):
                    return argument
        raise ValueError(f"Unsupported DEPS expression: {ast.dump(node)}")

    dependencies = None
    for statement in ast.parse(path.read_text()).body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if isinstance(target, ast.Name) and target.id == "vars":
            variables.update(value(statement.value))
        elif isinstance(target, ast.Name) and target.id == "deps":
            dependencies = value(statement.value)
    if dependencies is None:
        raise ValueError("DEPS has no literal deps table")
    return {"vars": variables, "deps": dependencies}

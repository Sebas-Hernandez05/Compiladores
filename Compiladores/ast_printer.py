from rich.tree import Tree
from rich import print
from model import Node

class RichASTPrinter:
    def build(self, node):
        if node is None:
            return Tree("[red]None[/red]")

        tree = Tree(f"[cyan]{type(node).__name__}[/cyan]")

        for field, value in vars(node).items():

            # Caso: lista de nodos
            if isinstance(value, list):
                branch = tree.add(f"[yellow]{field}[/yellow]")
                for item in value:
                    if isinstance(item, Node):
                        branch.add(self.build(item))
                    else:
                        branch.add(f"[green]{item}[/green]")

            # Caso: nodo hijo
            elif isinstance(value, Node):
                branch = tree.add(f"[yellow]{field}[/yellow]")
                branch.add(self.build(value))

            # Caso: valor simple
            else:
                tree.add(f"[magenta]{field}[/magenta]: [green]{value}[/green]")

        return tree
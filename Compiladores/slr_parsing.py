# slr_parsing.py
# ---------------------------------------------------
# LR(0) / SLR(1) parser generator (educational)
# - OOP + dataclasses
# - rich: ACTION/GOTO table
# - graphviz: DFA of LR(0) item sets (canonical collection)
#
# Visual DOT improvements:
#  1) ACCEPT state black
#  2) FOLLOW column grey (when generating SLR dot)
#  3) Conflict coloring: shift/reduce vs reduce/reduce
#
# Requirements:
#   pip install rich graphviz
#   system graphviz (dot) recommended for PNG rendering
#
# Run:
#   python slr_parsing.py
# ---------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Optional, FrozenSet, Iterable
from collections import defaultdict, deque

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

try:
	import graphviz  # python-graphviz
except ImportError:
	graphviz = None
	
console = Console()
Symbol = str


# ===================================================
# DATA STRUCTURES
# ===================================================

@dataclass(frozen=True)
class Production:
	lhs: Symbol
	rhs: Tuple[Symbol, ...]  # ε represented by empty tuple
	
	def __str__(self) -> str:
		if not self.rhs:
			return f"{self.lhs} → ε"
		return f"{self.lhs} → {' '.join(self.rhs)}"
		
		
@dataclass(frozen=True)
class Item:
	prod_index: int
	dot: int  # 0..len(rhs)
	
	
@dataclass
class Grammar:
	start: Symbol
	productions: List[Production]
	
	prods_by_lhs: Dict[Symbol, List[int]] = field(default_factory=dict)
	nonterminals: Set[Symbol] = field(default_factory=set)
	terminals: Set[Symbol] = field(default_factory=set)
	
	EPS: Symbol = "ε"
	EOF: Symbol = "$"
	
	def __post_init__(self) -> None:
		self._index()
		
	def _index(self) -> None:
		self.prods_by_lhs = defaultdict(list)
		self.nonterminals = {p.lhs for p in self.productions}
		
		rhs_symbols: Set[Symbol] = set()
		for i, p in enumerate(self.productions):
			self.prods_by_lhs[p.lhs].append(i)
			rhs_symbols.update(p.rhs)
			
		self.terminals = {s for s in rhs_symbols if s not in self.nonterminals and s != self.EPS}
		
		if self.start not in self.nonterminals:
			raise ValueError(f"Start symbol {self.start!r} is not a LHS nonterminal.")
			
	@property
	def all_symbols(self) -> Set[Symbol]:
		return set(self.nonterminals) | set(self.terminals)
		
	def augment(self) -> "Grammar":
		# Fixed augmented symbol S' (your preference)
		AUG = "S'"
		if AUG in self.nonterminals:
			raise ValueError("El símbolo aumentado S' ya existe en la gramática.")
		augmented = [Production(AUG, (self.start,))] + self.productions[:]
		return Grammar(start=AUG, productions=augmented)
		
		
@dataclass(frozen=True)
class State:
	items: FrozenSet[Item]
	
	
@dataclass
class DFA:
	states: List[State]
	transitions: Dict[Tuple[int, Symbol], int]  # (from_state, symbol) -> to_state
	
	
@dataclass
class ParserTables:
	action: Dict[Tuple[int, Symbol], Tuple[str, Optional[int]]]  # (state, terminal)-> ("s"/"r"/"acc", arg)
	goto: Dict[Tuple[int, Symbol], int]  # (state, nonterminal)-> state
	conflicts: List[str]
	conflict_kind_by_state: Dict[int, str] = field(default_factory=dict)  # "SR" or "RR" or "OTHER"
	
	
# ===================================================
# GENERATOR
# ===================================================

@dataclass
class LR0SLRGenerator:
	grammar: Grammar
	g: Grammar = field(init=False)
	
	first: Dict[Symbol, Set[Symbol]] = field(default_factory=dict)
	follow: Dict[Symbol, Set[Symbol]] = field(default_factory=dict)
	
	def __post_init__(self) -> None:
		# Always work on augmented grammar internally
		self.g = self.grammar.augment()
		
	# -----------------------------
	# LR(0) ITEMS
	# -----------------------------
	
	def closure(self, items: Iterable[Item]) -> FrozenSet[Item]:
		items_set: Set[Item] = set(items)
		changed = True
		while changed:
			changed = False
			for it in list(items_set):
				prod = self.g.productions[it.prod_index]
				if it.dot < len(prod.rhs):
					sym = prod.rhs[it.dot]
					if sym in self.g.nonterminals:
						for pidx in self.g.prods_by_lhs.get(sym, []):
							cand = Item(pidx, 0)
							if cand not in items_set:
								items_set.add(cand)
								changed = True
		return frozenset(items_set)
		
	def goto_items(self, state_items: FrozenSet[Item], symbol: Symbol) -> FrozenSet[Item]:
		moved: List[Item] = []
		for it in state_items:
			prod = self.g.productions[it.prod_index]
			if it.dot < len(prod.rhs) and prod.rhs[it.dot] == symbol:
				moved.append(Item(it.prod_index, it.dot + 1))
		return self.closure(moved) if moved else frozenset()
		
	def canonical_collection(self) -> DFA:
		# Initial state: closure({ S' -> • S })
		i0 = self.closure([Item(0, 0)])
		states: List[State] = [State(i0)]
		transitions: Dict[Tuple[int, Symbol], int] = {}
		seen: Dict[FrozenSet[Item], int] = {i0: 0}
		
		q = deque([0])
		symbols = sorted(self.g.all_symbols)
		
		while q:
			i = q.popleft()
			I = states[i].items
			for X in symbols:
				J = self.goto_items(I, X)
				if not J:
					continue
				if J not in seen:
					seen[J] = len(states)
					states.append(State(J))
					q.append(seen[J])
				transitions[(i, X)] = seen[J]
				
		return DFA(states=states, transitions=transitions)
		
	# -----------------------------
	# FIRST / FOLLOW (for SLR)
	# -----------------------------
	
	def compute_first_follow(self) -> None:
		first: Dict[Symbol, Set[Symbol]] = defaultdict(set)
		EPS = self.g.EPS
		
		# FIRST(terminal) = {terminal}
		for t in self.g.terminals:
			first[t].add(t)
		for nt in self.g.nonterminals:
			first[nt]  # ensure key exists
			
		def first_seq(seq: Tuple[Symbol, ...]) -> Set[Symbol]:
			if not seq:
				return {EPS}
			out: Set[Symbol] = set()
			for sym in seq:
				out |= (first[sym] - {EPS})
				if EPS not in first[sym]:
					break
			else:
				out.add(EPS)
			return out
			
		changed = True
		while changed:
			changed = False
			for p in self.g.productions:
				before = set(first[p.lhs])
				first[p.lhs] |= first_seq(p.rhs)
				if first[p.lhs] != before:
					changed = True
					
		follow: Dict[Symbol, Set[Symbol]] = defaultdict(set)
		follow[self.g.start].add(self.g.EOF)
		
		changed = True
		while changed:
			changed = False
			for p in self.g.productions:
				rhs = p.rhs
				for i, B in enumerate(rhs):
					if B not in self.g.nonterminals:
						continue
					beta = rhs[i + 1 :]
					fbeta = first_seq(beta)
					before = set(follow[B])
					follow[B] |= (fbeta - {EPS})
					if EPS in fbeta:
						follow[B] |= follow[p.lhs]
					if follow[B] != before:
						changed = True
						
		self.first = {k: set(v) for k, v in first.items()}
		self.follow = {k: set(v) for k, v in follow.items()}
		
	# -----------------------------
	# TABLE BUILDERS
	# -----------------------------
	
	def build_tables_lr0(self, dfa: DFA) -> ParserTables:
		action: Dict[Tuple[int, Symbol], Tuple[str, Optional[int]]] = {}
		goto: Dict[Tuple[int, Symbol], int] = {}
		conflicts: List[str] = []
		conflict_kind_by_state: Dict[int, str] = {}
		
		terminals = sorted(self.g.terminals | {self.g.EOF})
		
		# shifts and gotos from transitions
		for (i, X), j in dfa.transitions.items():
			if X in self.g.terminals:
				self._set_action(action, conflicts, conflict_kind_by_state, i, X, ("s", j))
			else:
				goto[(i, X)] = j
				
		# reductions
		for i, st in enumerate(dfa.states):
			for it in st.items:
				prod = self.g.productions[it.prod_index]
				if it.dot == len(prod.rhs):
					if it.prod_index == 0:
						self._set_action(action, conflicts, conflict_kind_by_state, i, self.g.EOF, ("acc", None))
					else:
						# LR(0): reduce on all terminals
						for a in terminals:
							self._set_action(action, conflicts, conflict_kind_by_state, i, a, ("r", it.prod_index))
							
		return ParserTables(action=action, goto=goto, conflicts=conflicts, conflict_kind_by_state=conflict_kind_by_state)
		
	def build_tables_slr(self, dfa: DFA) -> ParserTables:
		if not self.follow:
			self.compute_first_follow()
			
		action: Dict[Tuple[int, Symbol], Tuple[str, Optional[int]]] = {}
		goto: Dict[Tuple[int, Symbol], int] = {}
		conflicts: List[str] = []
		conflict_kind_by_state: Dict[int, str] = {}
		
		# shifts and gotos
		for (i, X), j in dfa.transitions.items():
			if X in self.g.terminals:
				self._set_action(action, conflicts, conflict_kind_by_state, i, X, ("s", j))
			else:
				goto[(i, X)] = j
				
		# reductions on FOLLOW(lhs)
		for i, st in enumerate(dfa.states):
			for it in st.items:
				prod = self.g.productions[it.prod_index]
				if it.dot == len(prod.rhs):
					if it.prod_index == 0:
						self._set_action(action, conflicts, conflict_kind_by_state, i, self.g.EOF, ("acc", None))
					else:
						for a in sorted(self.follow.get(prod.lhs, set())):
							self._set_action(action, conflicts, conflict_kind_by_state, i, a, ("r", it.prod_index))
							
		return ParserTables(action=action, goto=goto, conflicts=conflicts, conflict_kind_by_state=conflict_kind_by_state)
		
	def _set_action(
		self,
		action: Dict[Tuple[int, Symbol], Tuple[str, Optional[int]]],
		conflicts: List[str],
		conflict_kind_by_state: Dict[int, str],
		state: int,
		terminal: Symbol,
		entry: Tuple[str, Optional[int]],
	) -> None:
		key = (state, terminal)
		if key in action and action[key] != entry:
			old = action[key]
			kind = self._conflict_kind(old, entry)
			# store strongest kind per state (RR > SR > OTHER)
			prev = conflict_kind_by_state.get(state)
			conflict_kind_by_state[state] = self._merge_conflict_kind(prev, kind)
			
			conflicts.append(f"Conflicto {kind} en estado {state}, símbolo {terminal!r}: {old} vs {entry}")
			return
		action[key] = entry
		
	def _conflict_kind(self, a: Tuple[str, Optional[int]], b: Tuple[str, Optional[int]]) -> str:
		ka, _ = a
		kb, _ = b
		# shift/reduce
		if (ka == "s" and kb == "r") or (ka == "r" and kb == "s"):
			return "SR"
		# reduce/reduce
		if ka == "r" and kb == "r":
			return "RR"
		return "OTHER"
		
	def _merge_conflict_kind(self, prev: Optional[str], new: str) -> str:
		order = {"OTHER": 0, "SR": 1, "RR": 2}
		if prev is None:
			return new
		return new if order[new] > order[prev] else prev
		
	# -----------------------------
	# CLASSIFY
	# -----------------------------
	
	def classify(self) -> Tuple[bool, bool, DFA, ParserTables, ParserTables]:
		dfa = self.canonical_collection()
		lr0 = self.build_tables_lr0(dfa)
		is_lr0 = (len(lr0.conflicts) == 0)
		slr = self.build_tables_slr(dfa)
		is_slr = (len(slr.conflicts) == 0)
		return is_lr0, is_slr, dfa, lr0, slr
		
	# =================================================
	# DOT (Kalani-style HTML tables + your enhancements)
	# =================================================
	
	def to_graphviz(
		self,
		dfa: DFA,
		tables: ParserTables,
		filename: str = "lr_graph",
		render_png: bool = True,
		show_follow: bool = False,
	) -> str:
		"""
		show_follow:
		- False: no FOLLOW grey column
		- True : show FOLLOW grey column for completed reduce items
		(useful when rendering SLR table)
		"""
		dot = self._dfa_dot(dfa, tables, show_follow=show_follow)
		
		dot_path = f"{filename}.dot"
		with open(dot_path, "w", encoding="utf-8") as f:
			f.write(dot)
			
		if graphviz is None:
			console.print("[yellow]python-graphviz no está instalado; se generó solo el .dot[/yellow]")
			return dot_path
			
		if render_png:
			try:
				src = graphviz.Source(dot)
				src.format = "png"
				out = src.render(filename=filename, cleanup=True)
				return out
			except Exception as e:
				console.print(f"[yellow]No pude renderizar PNG (¿dot instalado?). Dejé .dot. Error: {e}[/yellow]")
				return dot_path
				
		return dot_path
		
	def _dfa_dot(self, dfa: DFA, tables: ParserTables, show_follow: bool) -> str:
		# Colors:
		#  - ACCEPT black
		#  - SR conflicts: lightsalmon
		#  - RR conflicts: lightcoral
		#  - otherwise: white
		SR_COLOR = "lightsalmon"
		RR_COLOR = "lightcoral"
		
		def is_accept_state(st: State) -> bool:
			# ACCEPT state contains item: (0) S' -> S •
			# augmented prod 0 has rhs length 1
			for it in st.items:
				if it.prod_index == 0:
					rhs_len = len(self.g.productions[0].rhs)
					if it.dot == rhs_len:
						return True
			return False
			
		def html_escape(s: str) -> str:
			return (
			s.replace("&", "&amp;")
			.replace("<", "&lt;")
			.replace(">", "&gt;")
			.replace('"', "&quot;")
			)
			
		lines: List[str] = []
		lines.append("digraph g {")
		lines.append('  fontname="Helvetica,Arial,sans-serif"')
		lines.append('  node [fontname="Courier New"]')
		lines.append('  edge [fontname="Helvetica,Arial,sans-serif"]')
		lines.append('  graph [fontsize=30 labelloc="t" label="" splines=true overlap=false rankdir="LR"];')
		lines.append("  ratio = auto;")
		
		# Nodes
		for i, st in enumerate(dfa.states):
			accept = is_accept_state(st)
			
			conflict_kind = tables.conflict_kind_by_state.get(i)
			if conflict_kind == "RR":
				fill = RR_COLOR
			elif conflict_kind == "SR":
				fill = SR_COLOR
			else:
				fill = "white"
				
			# ACCEPT overrides conflict coloring
			if accept:
				fill = "black"
				
			# state0 thicker border (like the example)
			penwidth = 5 if i == 0 else 1
			
			# For accept state, render text white
			row_font_open = '<font color="white">' if accept else ""
			row_font_close = "</font>" if accept else ""
			
			lines.append(
				f'  "state{i}" [ style="filled, bold" penwidth={penwidth} '
				f'fillcolor="{fill}" fontname="Courier New" shape="Mrecord" label=<'
				f'<table border="0" cellborder="0" cellpadding="3" bgcolor="{fill}">'
				f'<tr><td bgcolor="black" align="center" colspan="2">'
				f'<font color="white">State #{i}</font></td></tr>'
			)
			
			items_sorted = sorted(st.items, key=lambda x: (x.prod_index, x.dot))
			for it in items_sorted:
				p = self.g.productions[it.prod_index]
				rhs = list(p.rhs)
				rhs.insert(it.dot, "•")
				rhs_str = " ".join(rhs) if rhs else "•"
				item_txt = f"({it.prod_index}) {p.lhs} -> {rhs_str}"
				item_txt = html_escape(item_txt).replace("(", "&#40;").replace(")", "&#41;").replace("->", "-&gt;")
				
				# FOLLOW column only if requested AND it is a completed reduce item (not prod 0)
				follow_cell = ""
				if show_follow and (it.dot == len(p.rhs)) and (it.prod_index != 0):
					la = ", ".join(sorted(self.follow.get(p.lhs, set())))
					la = html_escape(la)
					follow_cell = f'<td bgcolor="lightgrey" align="right">{la}</td>'
				else:
					follow_cell = '<td></td>'
					
				lines.append(
					f'<tr><td align="left" port="r{it.prod_index}">{row_font_open}{item_txt} {row_font_close}</td>{follow_cell}</tr>'
				)
				
			lines.append("</table>> ];")
			
		# Edges
		for (i, X), j in sorted(dfa.transitions.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[1])):
			is_terminal = X in self.g.terminals
			penwidth = 1 if is_terminal else 5
			fontsize = 14 if is_terminal else 28
			fontcolor = "grey28" if is_terminal else "black"
			
			Xlbl = html_escape(X).replace('"', '\\"')
			lines.append(
				f'  state{i} -> state{j} [ penwidth={penwidth} fontsize={fontsize} fontcolor="{fontcolor}" label="{Xlbl}" ];'
			)
			
		lines.append("}")
		return "\n".join(lines)
		
	# -----------------------------
	# Pretty printing (rich)
	# -----------------------------
	
	def print_tables(self, dfa: DFA, tables: ParserTables, title: str) -> None:
		terminals = sorted(self.g.terminals | {self.g.EOF})
		nonterminals = sorted(self.g.nonterminals - {self.g.start})
		
		t = Table(title=title, show_lines=True)
		t.add_column("State", justify="right", style="cyan", no_wrap=True)
		for a in terminals:
			t.add_column(f"ACTION[{a}]", justify="center")
		for A in nonterminals:
			t.add_column(f"GOTO[{A}]", justify="center")
			
		for i in range(len(dfa.states)):
			row = [str(i)]
			for a in terminals:
				row.append(self._fmt_action(tables.action.get((i, a))))
			for A in nonterminals:
				j = tables.goto.get((i, A))
				row.append("" if j is None else str(j))
			t.add_row(*row)
			
		console.print(t)
		
		if tables.conflicts:
			console.print(Panel.fit("\n".join(tables.conflicts), title="Conflictos", border_style="red"))
		else:
			console.print(Panel.fit("Sin conflictos.", title="Diagnóstico", border_style="green"))
			
	def _fmt_action(self, entry: Optional[Tuple[str, Optional[int]]]) -> str:
		if entry is None:
			return ""
		kind, arg = entry
		if kind == "s":
			return f"s{arg}"
		if kind == "r":
			return f"r{arg}"
		if kind == "acc":
			return "acc"
		return str(entry)
		
		
# ===================================================
# LR PARSER DRIVER (recognition)
# ===================================================

@dataclass
class LRParser:
	gen: LR0SLRGenerator
	dfa: DFA
	tables: ParserTables
	
	def parse(self, tokens: List[Symbol]) -> bool:
		inp = tokens[:] + [self.gen.g.EOF]
		stack_states: List[int] = [0]
		stack_syms: List[Symbol] = []
		
		i = 0
		while True:
			s = stack_states[-1]
			a = inp[i]
			act = self.tables.action.get((s, a))
			
			if act is None:
				self._err(stack_states, stack_syms, inp, i, s, a)
				return False
				
			kind, arg = act
			if kind == "s":
				stack_syms.append(a)
				stack_states.append(int(arg))  # type: ignore[arg-type]
				i += 1
			elif kind == "r":
				pidx = int(arg)  # type: ignore[arg-type]
				prod = self.gen.g.productions[pidx]
				beta_len = len(prod.rhs)
				if beta_len:
					del stack_syms[-beta_len:]
					del stack_states[-beta_len:]
				t = stack_states[-1]
				ns = self.tables.goto.get((t, prod.lhs))
				if ns is None:
					console.print(f"[red]Error: no hay GOTO[{t}, {prod.lhs}] tras reducir {prod}[/red]")
					return False
				stack_syms.append(prod.lhs)
				stack_states.append(ns)
			elif kind == "acc":
				return True
			else:
				console.print(f"[red]Acción desconocida: {act}[/red]")
				return False
				
	def _err(self, st_states, st_syms, inp, i, state, lookahead):
		msg = Text()
		msg.append("Error de sintaxis\n", style="bold red")
		msg.append(f"  Estado: {state}\n", style="red")
		msg.append(f"  Lookahead: {lookahead!r}\n", style="red")
		msg.append(f"  Pila símbolos: {' '.join(st_syms) if st_syms else '(vacía)'}\n")
		msg.append(f"  Entrada restante: {' '.join(inp[i:])}\n")
		console.print(Panel(msg, border_style="red"))
		
		
# ===================================================
# GRAMMAR PARSER (tiny)
# ===================================================

def parse_grammar(text: str) -> Grammar:
	"""
	Format:
	- Start symbol is LHS of the first production.
	- Use '->' and '|' for alternatives.
	- Tokens separated by spaces.
	- ε can be written as 'ε' or empty RHS.
	
	Example:
	E -> E + T | T
	T -> id
	"""
	prods: List[Production] = []
	start: Optional[Symbol] = None
	
	for raw in text.splitlines():
		line = raw.strip()
		if not line or line.startswith("#"):
			continue
		if "->" not in line:
			raise ValueError(f"Línea inválida (falta '->'): {line}")
		lhs, rhs_all = [x.strip() for x in line.split("->", 1)]
		if start is None:
			start = lhs
			
		alts = [alt.strip() for alt in rhs_all.split("|")]
		for alt in alts:
			if alt == "" or alt == "ε":
				rhs: Tuple[Symbol, ...] = tuple()
			else:
				rhs = tuple(alt.split())
			prods.append(Production(lhs, rhs))
			
	if start is None:
		raise ValueError("Gramática vacía.")
	return Grammar(start=start, productions=prods)
	
	
# ===================================================
# DEMO / MAIN
# ============================================================

def main() -> None:
	# ----------------------------
	# Edita aquí tu gramática
	# ----------------------------
	GRAMMAR_TEXT = r"""
		# Ejemplo clásico SLR(1) (no LR(0)):             
		S  -> { F }
		F  -> F , C
		F  -> C
		C  -> id : V
		V  -> id
		V  -> num
		V  -> L
		L  -> [ E ]
		E -> E , V
		E -> V
	"""
	
	# Entrada (tokens separados por espacio)
	INPUT = "id + id + id"
	
	grammar = parse_grammar(GRAMMAR_TEXT)
	gen = LR0SLRGenerator(grammar)
	
	is_lr0, is_slr, dfa, lr0_tables, slr_tables = gen.classify()
	
	console.print(Panel.fit(
		f"Start (original): {grammar.start}\n"
		f"Start (augmented): {gen.g.start}\n"
		f"Producciones: {len(gen.g.productions)} (incluye producción 0)",
		title="Gramática",
		border_style="blue"
	))
	
	# LR(0) table and graph
	gen.print_tables(dfa, lr0_tables, title="Tabla LR(0)")
	out_lr0 = gen.to_graphviz(dfa, lr0_tables, filename="lr0_dfa", render_png=True, show_follow=False)
	console.print(f"[green]DFA LR(0) generado:[/green] {out_lr0}")
	
	# If not LR(0), show FOLLOW and SLR table + graph with FOLLOW column
	if not is_lr0:
		# FOLLOW already computed when building SLR tables, but ensure it exists:
		if not gen.follow:
			gen.compute_first_follow()
			
		ft = Table(title="FOLLOW (SLR)", show_lines=True)
		ft.add_column("No terminal", style="cyan", no_wrap=True)
		ft.add_column("FOLLOW", style="magenta")
		for nt in sorted(gen.g.nonterminals):
			ft.add_row(nt, "{ " + ", ".join(sorted(gen.follow.get(nt, set()))) + " }")
		console.print(ft)
		
		gen.print_tables(dfa, slr_tables, title="Tabla SLR(1)")
		out_slr = gen.to_graphviz(dfa, slr_tables, filename="slr_dfa", render_png=True, show_follow=True)
		console.print(f"[green]DFA SLR (con FOLLOW) generado:[/green] {out_slr}")
		
	# Parse input using best available
	console.print(Panel.fit(f"Entrada: {INPUT}", title="Prueba de parse", border_style="blue"))
	tokens = INPUT.split()
	
	if is_lr0:
		parser = LRParser(gen=gen, dfa=dfa, tables=lr0_tables)
		ok = parser.parse(tokens)
		console.print(Panel.fit("ACEPTADA ✅" if ok else "RECHAZADA ❌", title="Resultado (LR(0))",
		border_style="green" if ok else "red"))
	elif is_slr:
		parser = LRParser(gen=gen, dfa=dfa, tables=slr_tables)
		ok = parser.parse(tokens)
		console.print(Panel.fit("ACEPTADA ✅" if ok else "RECHAZADA ❌", title="Resultado (SLR)",
		border_style="green" if ok else "red"))
	else:
		console.print(Panel.fit("La gramática no es LR(0) ni SLR(1) (hay conflictos).",
		title="Resultado", border_style="red"))
		
	console.print(Panel.fit(
		f"LR(0): {'Sí' if is_lr0 else 'No'}\nSLR(1): {'Sí' if is_slr else 'No'}",
		title="Clasificación",
		border_style="cyan"
	))
	
	
if __name__ == "__main__":
	main()


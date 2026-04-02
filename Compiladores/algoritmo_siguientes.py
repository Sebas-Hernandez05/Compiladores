from collections import defaultdict #Para que empiece con conjuntos vacios

def calcular(producciones):
    no_terminales = set(producciones.keys()) #set convierte en conjunto para hacer busquedas mas rapidas

    #Recorrer todas las producciones para encontrar los terminales
    terminales = set()
    for lista in producciones.values():
        for produccion in lista:
            for simbolo in produccion:
                if simbolo != 'epsilon' and simbolo not in no_terminales:
                    terminales.add(simbolo)

    #Inicia los no terminales como falsos
    nullable = {}
    for nt in no_terminales:
        nullable[nt] = False

    FIRST = defaultdict(set)  #Diccionario de conjuntos para almacenar los primeros
    FOLLOW = defaultdict(set) #Diccionario de conjuntos para almacenar los siguientes

    for t in terminales:
        FIRST[t].add(t) #El primer de un terminal es el mismo terminal

    cambio = True
    while cambio:
        cambio = False

        for x, lista in producciones.items(): #Recorremos cada no terminal x y cada una de sus producciones
            for produccion in lista:
                simbolos = [s for s in produccion if s != 'epsilon'] #Obtenemos los simbolos sin epsilon
                k = len(simbolos) #Si la produccion es vacia, k sera 0

                #Si la produccion es vacia o todos los simbolos son nullable, x es nullable
                if k == 0 or all(nullable.get(s, False) for s in simbolos):
                    if not nullable[x]: #Solo marcamos cambio si x no era nullable antes
                        nullable[x] = True
                        cambio = True

                for i in range(k):
                    yi = simbolos[i] #Simbolo actual en la posicion i

                    #Si todos los simbolos ANTES de yi son nullable (o yi es el primero)
                    #entonces lo que puede iniciar yi tambien puede iniciar x
                    prefijo_nullable = (i == 0) or all(
                        nullable.get(simbolos[p], False) for p in range(i)
                    )

                    if prefijo_nullable:
                        antes = len(FIRST[x])
                        FIRST[x] |= FIRST[yi] #Agregamos a FIRST[x] todo lo que esta en FIRST[yi]
                        if len(FIRST[x]) != antes: #Solo marcamos cambio si el conjunto crecio
                            cambio = True

                    #Si todos los simbolos DESPUES de yi son nullable (o yi es el ultimo)
                    #entonces lo que puede seguir a x tambien puede seguir a yi
                    sufijo_nullable = (i == k - 1) or all(
                        nullable.get(simbolos[p], False) for p in range(i + 1, k)
                    )

                    if sufijo_nullable and yi in no_terminales:
                        antes = len(FOLLOW[yi])
                        FOLLOW[yi] |= FOLLOW[x] #Agregamos a FOLLOW[yi] todo lo que esta en FOLLOW[x]
                        if len(FOLLOW[yi]) != antes:
                            cambio = True

                    #Para cada simbolo yj que viene despues de yi
                    #si todo lo que hay entre yi e yj es nullable
                    #entonces FIRST[yj] puede seguir a yi
                    for j in range(i + 1, k):
                        yj = simbolos[j]
                        entre_nullable = (j == i + 1) or all(
                            nullable.get(simbolos[p], False) for p in range(i + 1, j)
                        )

                        if entre_nullable and yi in no_terminales:
                            antes = len(FOLLOW[yi])
                            FOLLOW[yi] |= FIRST[yj] #Lo que inicia yj puede seguir a yi
                            if len(FOLLOW[yi]) != antes:
                                cambio = True

    return nullable, dict(FIRST), dict(FOLLOW)


def imprimir(nullable, FIRST, FOLLOW, producciones):
    no_terminales = sorted(producciones.keys())
    print("\n" + "=" * 55)
    print(f"  {'Simbolo':<12} {'nullable':<10} {'FIRST':<18} FOLLOW")
    print("=" * 55)
    for nt in no_terminales:
        first_str  = "{" + ", ".join(sorted(FIRST.get(nt, set()))) + "}"
        follow_str = "{" + ", ".join(sorted(FOLLOW.get(nt, set()))) + "}"
        null_str   = "si" if nullable[nt] else "no"
        print(f"  {nt:<12} {null_str:<10} {first_str:<18} {follow_str}")
    print("=" * 55)


#----- ESCRIBE TU GRAMATICA AQUI -----#
gramatica = {
    'Z': [['d'], ['X', 'Y', 'Z']],
    'Y': [['c'], ['epsilon']],
    'X': [['Y'], ['a']],
}

nullable, FIRST, FOLLOW = calcular(gramatica)
imprimir(nullable, FIRST, FOLLOW, gramatica)
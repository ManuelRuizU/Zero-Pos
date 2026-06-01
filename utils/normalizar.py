_MINUSCULAS = {
    'de', 'del', 'la', 'las', 'los', 'el',
    'y', 'e', 'o', 'a', 'en', 'con', 'por',
    'para', 'sin', 'al', 'un', 'una', 'unos', 'unas',
}


def normalizar_nombre(texto: str) -> str:
    if not texto:
        return ""
    palabras = texto.strip().lower().split()
    resultado = []
    for i, p in enumerate(palabras):
        if i == 0 or p not in _MINUSCULAS:
            resultado.append(p.capitalize())
        else:
            resultado.append(p)
    return ' '.join(resultado)


def chunk_text(text: str, max_chars: int = 8000) -> list[str]:
    
    paragraphs = [p for p in text.split('\n\n') if p.strip()]
    cur_par = ''

    chanks = []
    for parag in paragraphs:
        if len(cur_par) + len(parag) > max_chars:
            chanks.append(cur_par)
            cur_par = '\n\n' + parag
        else:
            cur_par += '\n\n' + parag
    chanks.append(cur_par)

    return chanks
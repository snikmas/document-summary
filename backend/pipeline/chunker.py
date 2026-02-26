from backend.config import MAX_CHUNK_SIZE

def chunk_text(text: str, max_chars: int = MAX_CHUNK_SIZE) -> list[str]:

    paragraphs = [p for p in text.split('\n\n') if p.strip()]
    cur_par = ''

    chunks = []
    for parag in paragraphs:
        # split oversized paragraphs that exceed max_chars on their own
        if len(parag) > max_chars:
            if cur_par:
                chunks.append(cur_par)
                cur_par = ''
            for i in range(0, len(parag), max_chars):
                chunks.append(parag[i:i + max_chars])
        elif len(cur_par) + len(parag) > max_chars:
            chunks.append(cur_par)
            cur_par = parag
        else:
            if cur_par:
                cur_par += '\n\n' + parag
            else:
                cur_par = parag
    if cur_par:
        chunks.append(cur_par)

    return chunks
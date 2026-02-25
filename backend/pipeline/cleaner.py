import unicodedata
import re

def clean_text(text: str) -> str:
    # text is a .. list of lines? or what
    # 1. strip null bytes
    text = text.replace('\x00', '')
    # 2. normalize unicode
    text = unicodedata.normalize('NFKC', text)
    # 3. per-line trim
    lines = [line.strip() for line in text.splitlines()]
    text = '\n'.join(lines)

    # 4. collapse spaces (not newlines)
    text = re.sub(r'[^\S\n]+', ' ', text)        
    # 5. max 2 consecutive newlines     
    text = re.sub(r'\n{3,}', '\n\n', text)       
    
    return text.strip()

from pypdf import PdfReader
from docx import Document
from bs4 import BeautifulSoup
import io
import csv

from backend.pipeline.detector import detect_file_type


def extract_text(file_bytes: bytes) -> str:

    file_format = detect_file_type(file_bytes)

    match file_format: # file is bytes
        case 'pdf':
            content = extract_pdf(file_bytes)
        case 'docx':
            content = extract_docx(file_bytes)
        case 'txt':
            content = extract_txt(file_bytes)
        case 'html':
            content = extract_html(file_bytes)
        case 'csv':
            content = extract_csv(file_bytes)
        case _:
            raise ValueError(f"Unsupported file type: {file_format}")
    

    return content

def extract_pdf(file_bytes):
    file = io.BytesIO(file_bytes)
    reader = PdfReader(file)
    #what if its a large document? chunks?
    content = '\n'.join(p.extract_text() or '' for p in reader.pages)
    return content

# need bytesio
def extract_docx(file_bytes):
    doc = Document(io.BytesIO(file_bytes))
    content = '\n'.join(p.text for p in doc.paragraphs) #idk
    return content

# for txt - just decode it
def extract_txt(file_bytes):
    return file_bytes.decode('utf-8', errors='replace')
    

def extract_html(file_bytes):

    soup = BeautifulSoup(file_bytes, 'html.parser')

    for html_text in soup(['script', 'style']):
        html_text.decompose()

    visible_content = soup.get_text(separator=' ', strip=True)
    return visible_content

# just decode it
def extract_csv(file_bytes):
    file = file_bytes.decode('utf-8', errors='replace')

    csv_file = io.StringIO(file)
    reader = csv.reader(csv_file)
    
    rows = [', '.join(row) for row in reader]
    
    return '\n'.join(rows)
    

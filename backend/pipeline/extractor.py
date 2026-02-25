from pypdf import PdfReader
from docx import Document
from bs4 import BeautifulSoup
import io
import csv

from backend.pipeline.detector import detect_file_type


def extract_text(file_bytes):
    file = io.BytesIO(file_bytes)
    #1. check if a file ok? format or correptuer
    file_format = detect_file_type(file)

    match file: # file is bytes
        case 'pdf':
            content = extract_pdf(file)
        case 'docx':
            content = extract_docx(file)
        case 'txt':
            content = extract_txt(file)
        case 'html':
            content = extract_html(file)
        case 'csv':
            content = extract_csv(file)


def extract_pdf(file):
    reader = PdfReader(file)
    #what if its a large document? chunks?
    content = '\n'.join(p.extract_text() for p in reader.pages)
    return content

def extract_docx(file):
    doc = Document(file)
    content = '\n'.join(doc.paragraphs[p].text for p in doc.paragraphs) #idk
    pass

def extract_txt(file):
    file.seek(0)
    content = ''
    for line in file:
        content += line.decode('utf-8').strip()
    return content

def extract_html(file):
    soup = BeautifulSoup(file, 'html.parser')

    for html_text in soup(['script', 'style']):
        html_text.decompose()

    visible_content = soup.get_text(separator=' ', strip=True)
    return visible_content

def extract_csv(file):
    csv_reader = csv.reader(file.decode('utf-8').splitlines())
    content = [p for p in csv_reader]
    return content.join('\n')

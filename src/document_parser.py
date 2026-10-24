"""
Módulo para extracción y procesamiento de documentos completos (PDF, EPUB, TXT, MD).
Segmenta el texto en párrafos y oraciones estructuradas para navegación precisa.
"""

import os
import re
import zipfile
from dataclasses import dataclass, field
from typing import List, Optional
from bs4 import BeautifulSoup

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False


def clean_text_for_speech(text: str) -> str:
    """Limpia caracteres especiales, markdown y urls para lectura natural."""
    if not text:
        return ""
    # Quitar bloques de código markdown pero conservar contenido
    t = re.sub(r'```[a-zA-Z0-9_-]*\n?(.*?)```', r'\1', text, flags=re.DOTALL)
    t = re.sub(r'`(.*?)`', r'\1', t)
    # Reemplazar URLs completas por la palabra 'enlace'
    t = re.sub(r'https?://\S+', 'enlace', t)
    # Quitar marcas de markdown decorativas (*, #, _, ~, >, |)
    t = re.sub(r'[*#_~>|]', '', t)
    # Limpiar líneas decorativas largas o caracteres ASCII art
    t = re.sub(r'[-=─━═_]{3,}', ' ', t)
    # Eliminar espacios redundantes y saltos excesivos
    t = re.sub(r'[ \t]+', ' ', t)
    return t.strip()


def split_into_sentences(paragraph: str) -> List[str]:
    """Divide un párrafo en oraciones individuales para navegación por línea/oración."""
    if not paragraph:
        return []
    # Divide en signos de puntuación (. ! ?) seguidos de mayúscula, comillas, guion largo o apertura
    parts = re.split(r'(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑa-záéíóúñ—\"\'«¿¡])', paragraph)
    sentences = [p.strip() for p in parts if p.strip()]
    return sentences if sentences else [paragraph.strip()]


@dataclass
class Document:
    title: str
    file_path: Optional[str]
    paragraphs: List[str] = field(default_factory=list)
    sentences: List[List[str]] = field(default_factory=list)
    total_words: int = 0

    def __post_init__(self):
        if self.paragraphs and not self.sentences:
            self.sentences = [split_into_sentences(p) for p in self.paragraphs]
        if not self.total_words:
            self.total_words = sum(len(p.split()) for p in self.paragraphs)

    @property
    def total_paragraphs(self) -> int:
        return len(self.paragraphs)

    def get_paragraph(self, index: int) -> str:
        if 0 <= index < len(self.paragraphs):
            return self.paragraphs[index]
        return ""

    def get_sentences_for(self, para_index: int) -> List[str]:
        if 0 <= para_index < len(self.sentences):
            return self.sentences[para_index]
        return []

    def estimated_duration_minutes(self, speed: float = 1.25) -> float:
        """Estima la duración total en minutos a una velocidad dada (aprox 150 palabras/min)."""
        words_per_minute = 150.0 * speed
        return round(self.total_words / max(words_per_minute, 1.0), 1)


class DocumentParser:
    """Extractor universal de texto para libros y documentos."""

    @staticmethod
    def load_file(file_path: str) -> Document:
        """Carga y parsea un archivo según su extensión."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"No existe el archivo: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        title = os.path.splitext(os.path.basename(file_path))[0]

        if ext == ".pdf":
            paragraphs = DocumentParser._parse_pdf(file_path)
        elif ext == ".epub":
            paragraphs = DocumentParser._parse_epub(file_path)
        elif ext in (".txt", ".md", ".org", ".rst"):
            paragraphs = DocumentParser._parse_plaintext(file_path)
        else:
            # Intentar como texto plano para cualquier otra extensión
            paragraphs = DocumentParser._parse_plaintext(file_path)

        # Filtrar párrafos vacíos o insignificantes (números de página sueltos, etc.)
        cleaned_paragraphs = []
        for p in paragraphs:
            cleaned = clean_text_for_speech(p)
            # Ignorar si es solo un número aislado (número de página) o muy corto sin letras
            if len(cleaned) < 2:
                continue
            if re.match(r'^\d+$', cleaned.strip()):
                continue
            cleaned_paragraphs.append(cleaned)

        if not cleaned_paragraphs:
            cleaned_paragraphs = ["El documento no contiene texto legible."]

        sentences = [split_into_sentences(p) for p in cleaned_paragraphs]
        return Document(
            title=title,
            file_path=file_path,
            paragraphs=cleaned_paragraphs,
            sentences=sentences
        )

    @staticmethod
    def from_text(raw_text: str, title: str = "Texto Seleccionado") -> Document:
        """Crea un documento a partir de una cadena de texto (portapapeles o pegado)."""
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        paragraphs = []
        current_chunk = []

        for line in lines:
            # Si la línea parece el inicio de un nuevo párrafo o separación
            if current_chunk and (len(line) > 0 and line[0] in "—•-*0123456789" or len(current_chunk[-1]) < 50):
                paragraphs.append(" ".join(current_chunk))
                current_chunk = [line]
            else:
                current_chunk.append(line)

        if current_chunk:
            paragraphs.append(" ".join(current_chunk))

        cleaned_paragraphs = [clean_text_for_speech(p) for p in paragraphs if clean_text_for_speech(p)]
        if not cleaned_paragraphs:
            cleaned_paragraphs = [clean_text_for_speech(raw_text)] if clean_text_for_speech(raw_text) else ["No hay texto para leer."]

        sentences = [split_into_sentences(p) for p in cleaned_paragraphs]
        return Document(
            title=title,
            file_path=None,
            paragraphs=cleaned_paragraphs,
            sentences=sentences
        )

    @staticmethod
    def _parse_pdf(file_path: str) -> List[str]:
        """Extrae texto de un archivo PDF estructurando por párrafos."""
        if not PYPDF_AVAILABLE:
            # Fallback a pdftotext si existe en el sistema
            return DocumentParser._parse_pdf_fallback(file_path)

        paragraphs = []
        try:
            reader = PdfReader(file_path)
            for page in reader.pages:
                text = page.extract_text()
                if not text:
                    continue
                # Desunir palabras partidas con guión al final de línea ("trans- porte" -> "transporte")
                text = re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', text)
                # Separar por dobles saltos de línea
                page_paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
                for p in page_paras:
                    # Unir líneas rotas dentro del mismo párrafo
                    single_line_p = " ".join(p.splitlines())
                    paragraphs.append(single_line_p)
        except Exception as e:
            # Si falla pypdf, intentar con pdftotext
            fallback = DocumentParser._parse_pdf_fallback(file_path)
            if fallback:
                return fallback
            paragraphs.append(f"Error al leer PDF: {e}")

        return paragraphs

    @staticmethod
    def _parse_pdf_fallback(file_path: str) -> List[str]:
        """Usa el comando pdftotext si está disponible en Linux."""
        import subprocess
        try:
            res = subprocess.run(["pdftotext", file_path, "-"], capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and res.stdout.strip():
                text = re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', res.stdout)
                return [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
        except Exception:
            pass
        return []

    @staticmethod
    def _parse_epub(file_path: str) -> List[str]:
        """Extrae texto de un archivo EPUB analizando el paquete ZIP interno."""
        paragraphs = []
        try:
            with zipfile.ZipFile(file_path, "r") as z:
                # Buscar archivos XHTML o HTML de capítulos
                chapter_files = []
                for name in z.namelist():
                    lower = name.lower()
                    if lower.endswith((".html", ".xhtml", ".htm")) and not "nav" in lower and not "toc" in lower:
                        chapter_files.append(name)

                # Si no filtró o quedaron pocos, incluir todos los HTML
                if not chapter_files:
                    chapter_files = [n for n in z.namelist() if n.lower().endswith((".html", ".xhtml", ".htm"))]

                # Ordenar alfabéticamente/secuencialmente
                chapter_files.sort()

                for chapter_path in chapter_files:
                    try:
                        content = z.read(chapter_path).decode("utf-8", errors="ignore")
                        soup = BeautifulSoup(content, "html.parser")

                        # Extraer por elementos de bloque
                        for elem in soup.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "li"]):
                            text = elem.get_text().strip()
                            if text:
                                paragraphs.append(text)
                    except Exception:
                        continue
        except Exception as e:
            paragraphs.append(f"Error al leer EPUB: {e}")

        return paragraphs

    @staticmethod
    def _parse_plaintext(file_path: str) -> List[str]:
        """Lee archivos de texto plano o markdown divididos por párrafos."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            # Dividir por dobles saltos de línea (párrafos estándar)
            raw_paras = re.split(r'\n\s*\n', content)
            paragraphs = [" ".join(p.splitlines()).strip() for p in raw_paras if p.strip()]
            return paragraphs
        except Exception as e:
            return [f"Error al abrir archivo: {e}"]

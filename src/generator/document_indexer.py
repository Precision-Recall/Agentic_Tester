"""
Document Indexer — Processes local files (PDF, DOCX, TXT) into a FAISS vector store
for Retrieval-Augmented Generation (RAG).
"""

import logging
from pathlib import Path
from typing import Optional

from langchain_community.document_loaders import (
    PyPDFLoader, Docx2txtLoader, TextLoader, UnstructuredMarkdownLoader
)
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config import Settings

logger = logging.getLogger(__name__)


async def index_documents(
    folder_path: str,
    settings: Settings,
) -> Optional[FAISS]:
    """Load, chunk, and index documents from a local folder into a vector store.

    Args:
        folder_path: Path to the local directory containing requirement docs.
        settings: Application settings.

    Returns:
        FAISS vector store, or None if no valid documents found.
    """
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        logger.warning(f"Document folder not found or invalid: {folder_path}")
        return None

    logger.info(f"Indexing documents in: {folder_path}")

    # 1. Load documents
    docs = []
    supported_extensions = {
        ".pdf": PyPDFLoader,
        ".docx": Docx2txtLoader,
        ".txt": TextLoader,
        ".md": UnstructuredMarkdownLoader,
    }

    for file_path in folder.rglob("*"):
        if not file_path.is_file():
            continue

        ext = file_path.suffix.lower()
        if ext in supported_extensions:
            loader_class = supported_extensions[ext]
            try:
                loader = loader_class(str(file_path))
                file_docs = loader.load()
                # Add source metadata
                for d in file_docs:
                    d.metadata["source"] = file_path.name
                docs.extend(file_docs)
                logger.info(f"Loaded {len(file_docs)} pages/sections from {file_path.name}")
            except Exception as e:
                logger.error(f"Failed to load {file_path.name}: {e}")

    if not docs:
        logger.warning(f"No supported documents found in {folder_path}")
        return None

    # 2. Split into chunks
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.RAG_CHUNK_SIZE,
        chunk_overlap=settings.RAG_CHUNK_OVERLAP,
    )
    chunks = text_splitter.split_documents(docs)
    logger.info(f"Split {len(docs)} documents into {len(chunks)} chunks")

    # 3. Create vector store
    try:
        embeddings = GoogleGenerativeAIEmbeddings(
            model="models/text-embedding-004",
            google_api_key=settings.GOOGLE_API_KEY,
        )
        vector_store = FAISS.from_documents(chunks, embeddings)
        logger.info("Vector store created successfully")
        return vector_store
    except Exception as e:
        logger.error(f"Failed to create vector store: {e}")
        return None


async def retrieve_relevant_context(
    vector_store: FAISS,
    query: str,
    settings: Settings,
) -> str:
    """Retrieve relevant document chunks for a given query.

    Args:
        vector_store: The populated FAISS index.
        query: The user's generation prompt.
        settings: Application settings.

    Returns:
        A concatenated string of relevant context chunks.
    """
    if not vector_store:
        return ""

    logger.info(f"Retrieving top {settings.RAG_TOP_K} chunks for query")
    retriever = vector_store.as_retriever(search_kwargs={"k": settings.RAG_TOP_K})
    
    try:
        # We use ainvoke if available, otherwise fallback to invoke
        if hasattr(retriever, "ainvoke"):
            relevant_docs = await retriever.ainvoke(query)
        else:
            relevant_docs = retriever.invoke(query)
            
        context_parts = []
        for i, doc in enumerate(relevant_docs, 1):
            source = doc.metadata.get("source", "Unknown")
            context_parts.append(f"--- Document: {source} (Excerpt {i}) ---\n{doc.page_content}")
            
        return "\n\n".join(context_parts)
    except Exception as e:
        logger.error(f"Error retrieving context: {e}")
        return ""

"""CPU-only pretrained Chinese static word vectors. No private text leaves this process."""

from contextlib import nullcontext
from functools import lru_cache
from threading import RLock

import numpy as np
import spacy

MODEL_ID = "zh_core_web_md-3.8.0-mean300-v1"
_lock = RLock()


@lru_cache(maxsize=1)
def model():
    return spacy.load(
        "zh_core_web_md",
        exclude=["tok2vec", "tagger", "parser", "ner", "attribute_ruler", "lemmatizer", "senter"],
    )


def encode(text: str) -> tuple[list[float] | None, str]:
    # Serialize access to spaCy's tokenizer and release transient strings when supported.
    with _lock:
        nlp = model()
        zone = nlp.memory_zone() if hasattr(nlp, "memory_zone") else nullcontext()
        with zone:
            document = nlp.make_doc(text)
            tokens = [
                token.text.lower()
                for token in document
                if not token.is_space and not token.is_punct
            ]
            vectors = [
                token.vector
                for token in document
                if token.has_vector
                and token.vector_norm > 0
                and not token.is_stop
                and not token.is_punct
            ]
            if not vectors:
                return None, " ".join(tokens)
            vector = np.asarray(vectors, dtype=np.float32).mean(axis=0)
            norm = float(np.linalg.norm(vector))
            return (vector / norm).tolist() if norm > 0 else None, " ".join(tokens)

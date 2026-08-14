from abc import ABC, abstractmethod
from typing import Optional, Iterator


class AIBackend(ABC):
    @abstractmethod
    def chat(self, messages: list[dict], model: str, callback=None) -> Iterator[str]:
        pass

    @abstractmethod
    def get_models(self) -> list[str]:
        pass

    @abstractmethod
    def get_status(self) -> str:
        pass

    @abstractmethod
    def upload_file(self, file_path: str) -> Optional[str]:
        pass

    def reset_conversation(self):
        pass
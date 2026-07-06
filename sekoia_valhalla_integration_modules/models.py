from pydantic import BaseModel, Field

DEMO_API_KEY = "1" * 64


class SekoiaValhallaIntegrationModuleConfiguration(BaseModel):
    api_key: str = Field(default=DEMO_API_KEY)
    sekoia_api_key: str = Field(default="")
    sekoia_base_url: str = Field(default="https://api.sekoia.io")

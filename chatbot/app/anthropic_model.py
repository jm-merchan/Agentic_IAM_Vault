"""LangChain's Anthropic adapter with explicit OAuth Bearer authentication."""
from functools import cached_property

from anthropic import Omit, AsyncAnthropic
import httpx2
from .http_capture import CapturedModelMixin, model_http_client
from langchain_anthropic import ChatAnthropic


class FederatedChatAnthropic(CapturedModelMixin, ChatAnthropic):
    @cached_property
    def _client_params(self):
        # The locked LangChain version exposes api_key, but not auth_token.
        # Keep the token in its SecretStr slot and hand it to the SDK as OAuth.
        params = dict(super()._client_params)
        params['auth_token'] = params.pop('api_key')
        params['api_key'] = None
        # Suppress an ambient SDK API key as well as the x-api-key header.
        params['default_headers'] = {**params['default_headers'], 'X-Api-Key': Omit()}
        return params

    @cached_property
    def _async_client(self):
        return AsyncAnthropic(**self._client_params,
                              http_client=model_http_client(http_module=httpx2, proxy=self.anthropic_proxy or None))

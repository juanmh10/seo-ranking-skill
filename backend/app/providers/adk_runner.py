from collections.abc import AsyncIterator

from app.domain.model_runner import ModelRequest, ModelResponse, ModelStreamEvent


class AdkModelRunner:
    """One ADK runner and one memory-only session per benchmark repetition."""

    async def run(self, request: ModelRequest) -> ModelResponse:
        try:
            from google.adk.agents import LlmAgent, RunConfig
            from google.adk.apps import App
            from google.adk.models import Gemini
            from google.adk.runners import Runner
            from google.adk.sessions import InMemorySessionService
            from google.genai import types
        except ImportError as error:
            raise RuntimeError(
                "Install the backend model extra: pip install -e './backend[model]'"
            ) from error

        model = Gemini(
            model=request.model_id,
            client_kwargs={
                "vertexai": True,
                "project": request.project,
                "location": request.location,
            },
        )
        generation_config = {
            "temperature": request.temperature,
            "top_p": request.top_p,
            "seed": request.seed,
            "max_output_tokens": request.max_output_tokens,
        }
        if request.response_json_schema is not None:
            generation_config["response_mime_type"] = "application/json"
            generation_config["response_json_schema"] = request.response_json_schema
        agent = LlmAgent(
            name="subject_model",
            model=model,
            instruction=request.system_prompt,
            generate_content_config=types.GenerateContentConfig(**generation_config),
        )
        app = App(name="source_manipulation_benchmark", root_agent=agent)
        session_service = InMemorySessionService()
        runner = Runner(app=app, session_service=session_service)
        session = await session_service.create_session(app_name=app.name, user_id="benchmark")
        source_context = "\n\n".join(
            f'<source position="{index}">\n{text}\n</source>'
            for index, text in enumerate(request.source_texts, start=1)
        )
        context = types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"Retrieved sources:\n{source_context}")],
        )
        user_message = types.Content(
            role="user", parts=[types.Part.from_text(text=request.user_prompt)]
        )
        response_text: str | None = None
        model_version: str | None = None
        input_tokens = output_tokens = total_tokens = None
        invocation_id: str | None = None
        async for event in runner.run_async(
            user_id="benchmark",
            session_id=session.id,
            new_message=user_message,
            run_config=RunConfig(
                model_input_context=[context] if request.source_texts else None,
                max_llm_calls=1,
            ),
        ):
            if event.usage_metadata is not None:
                usage = event.usage_metadata
                input_tokens = usage.prompt_token_count
                output_tokens = usage.candidates_token_count
                total_tokens = usage.total_token_count
            if event.model_version:
                model_version = event.model_version
            if event.is_final_response() and event.author == agent.name and event.content:
                response_text = "".join(
                    part.text or "" for part in event.content.parts or [] if not part.thought
                ).strip()
                invocation_id = event.invocation_id

        if not response_text:
            raise RuntimeError("Model returned no usable final text")
        return ModelResponse(
            text=response_text,
            model_id_actual=model_version or request.model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            request_id=None,
            trace_id=invocation_id,
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        try:
            from google.adk.agents import LlmAgent
            from google.adk.agents.run_config import RunConfig, StreamingMode
            from google.adk.apps import App
            from google.adk.models import Gemini
            from google.adk.runners import Runner
            from google.adk.sessions import InMemorySessionService
            from google.genai import types
        except ImportError as error:
            raise RuntimeError(
                "Install the backend model extra: pip install -e './backend[model]'"
            ) from error

        model = Gemini(
            model=request.model_id,
            client_kwargs={
                "vertexai": True,
                "project": request.project,
                "location": request.location,
            },
        )
        generation_config = {
            "temperature": request.temperature,
            "top_p": request.top_p,
            "seed": request.seed,
            "max_output_tokens": request.max_output_tokens,
        }
        agent = LlmAgent(
            name="interactive_model",
            model=model,
            instruction=request.system_prompt,
            generate_content_config=types.GenerateContentConfig(**generation_config),
        )
        app = App(name="source_manipulation_interactive", root_agent=agent)
        session_service = InMemorySessionService()
        runner = Runner(app=app, session_service=session_service)
        session = await session_service.create_session(
            app_name=app.name, user_id="interactive"
        )
        source_context = "\n\n".join(
            f'<source position="{index}">\n{text}\n</source>'
            for index, text in enumerate(request.source_texts, start=1)
        )
        context = types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"Retrieved sources:\n{source_context}")],
        )
        user_message = types.Content(
            role="user", parts=[types.Part.from_text(text=request.user_prompt)]
        )
        text_parts: list[str] = []
        final_text: str | None = None
        model_version: str | None = None
        input_tokens = output_tokens = total_tokens = None
        invocation_id: str | None = None
        async for event in runner.run_async(
            user_id="interactive",
            session_id=session.id,
            new_message=user_message,
            run_config=RunConfig(
                model_input_context=[context] if request.source_texts else None,
                max_llm_calls=1,
                streaming_mode=StreamingMode.SSE,
            ),
        ):
            if event.usage_metadata is not None:
                usage = event.usage_metadata
                input_tokens = usage.prompt_token_count
                output_tokens = usage.candidates_token_count
                total_tokens = usage.total_token_count
            if event.model_version:
                model_version = event.model_version
            if event.partial and event.content:
                delta = "".join(
                    part.text or "" for part in event.content.parts or [] if not part.thought
                )
                if delta:
                    text_parts.append(delta)
                    yield ModelStreamEvent(text_delta=delta)
            if event.is_final_response() and event.author == agent.name and event.content:
                final_text = "".join(
                    part.text or "" for part in event.content.parts or [] if not part.thought
                ).strip()
                invocation_id = event.invocation_id

        response_text = final_text or "".join(text_parts).strip()
        if not response_text:
            raise RuntimeError("Model returned no usable final text")
        response = ModelResponse(
            text=response_text,
            model_id_actual=model_version or request.model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            request_id=None,
            trace_id=invocation_id,
        )
        yield ModelStreamEvent(response=response)

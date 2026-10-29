"""Explicit diagnostic: list models by default; generation requires --generate."""
import argparse
import asyncio
from contextlib import aclosing
import os
import sys
from pydantic import ValidationError
from backend.app.llm import create_provider
from backend.app.llm.schemas import ProviderConfig, ModelSelection, GenerationRequest, Message, ProviderError


async def run(args):
    provider = None
    try:
        config = ProviderConfig(id="diagnostic", name="Diagnostic", kind=args.provider,
                                base_url=args.base_url or
                                         {"openai": "https://api.openai.com/v1", "ollama": "http://127.0.0.1:11434"}[
                                             args.provider],
                                timeout=args.timeout, connect_timeout=min(args.timeout, 10),
                                api_key=os.getenv("FOLLIANT_LLM_API_KEY") or (
                                    os.getenv("OPENAI_API_KEY") if args.provider == "openai" else None))
        provider = create_provider(config)
        models = await provider.list_models()
        print("Connection OK. Available models:")
        for model in models:
            print(" -", model.id)
        if args.generate:
            request = GenerationRequest(selection=ModelSelection(provider_id="diagnostic", model=args.model),
                                        messages=[Message(role="user", text="Reply with a short greeting.")])
            if args.stream:
                async with aclosing(provider.stream(request)) as stream:
                    async for event in stream:
                        if event.type == "text_delta":
                            print(event.text, end="", flush=True)
                        elif event.type == "completed":
                            print("\nFinish:", event.response.finish_reason)
            else:
                result = await provider.generate(request)
                print(result.message.text)
                print("Finish:", result.finish_reason)
        return 0
    except ProviderError as exc:
        print(f"LLM diagnostic failed ({exc.code}): {exc}", file=sys.stderr)
        return 1
    except ValidationError:
        print("Invalid diagnostic configuration. Check URL, model and timeouts.", file=sys.stderr)
        return 1
    finally:
        if provider:
            await provider.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=["openai", "ollama"])
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--generate", action="store_true", help="Make an actual generation request (may incur costs)")
    parser.add_argument("--stream", action="store_true")
    args = parser.parse_args()
    if args.generate and not args.model:
        parser.error("--generate requires --model")
    if args.stream and not args.generate:
        parser.error("--stream requires --generate")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
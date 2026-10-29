# LLM Providers

Слой `backend/app/llm` предоставляет асинхронный Python API, независимый от календаря, MCP и будущего чата. Используются официальные SDK `openai==3.40.0` и `ollama==0.6.3`. Он возвращает вызовы инструментов, но **никогда не выполняет** их.

## Ответственность компонентов

- `schemas.py`: ProviderConfig, ModelSelection, Message, ToolDefinition, ToolCall, GenerationRequest, ModelResponse, StreamEvent, ModelInfo и безопасная ProviderError.
- `base.py`: интерфейс ModelProvider, последовательное выполнение в одном экземпляре адаптера и классификация ошибок.
- `openai_provider.py`: OpenAI Responses API, включая потоковые события и данные продолжения.
- `ollama_provider.py`: native Ollama `/api/chat`, JSON-аргументы функций, накопление content/thinking/tool_calls.
- `credentials.py`: системное хранилище ключей через keyring. Блокирующие операции ОС вынесены в `asyncio.to_thread`.
- `services/llm_providers.py`: единственная точка SQL-доступа к настройкам LLM, активная модель и управление временем жизни адаптеров.
- `api/llm_router.py`: локальный API настроек для будущего интерфейса. REST-генерации, чата и AgentRunner нет.

## Провайдер и модель

Таблица `llm_providers` хранит ID, тип, название, base_url, timeout, connect_timeout и ссылку на запись системного хранилища. Таблица `llm_selection` содержит единственную активную настройку: provider_id, model, необязательные temperature и max_output_tokens. Модель меняется без создания нового подключения. Удаление провайдера сбрасывает связанную активную настройку.

Миграция `f1a205c8b910` добавляет эти две таблицы; существующие данные и схемы MCP не меняются. Подключений по умолчанию нет. Выбор модели сохраняется без сетевого запроса: офлайн-настройка допустима, доступность проверяется отдельно.

Для будущего UI предлагается отдельная карточка **«Модели и подключения»** в настройках:

1. Список подключений с добавлением/редактированием адреса, ключа и времени ожидания.
2. Кнопка «Проверить подключение / обновить модели».
3. Отдельный выбор активного провайдера и модели из его списка; ручной ввод ID модели остаётся полезен при ограничениях `/models`.

Возвращаемое `has_api_key` означает наличие сохранённой ссылки, а не успешную авторизацию. Форма ключа всегда пустая: отсутствие api_key в PATCH сохраняет прежний ключ, null или пустая строка удаляет его. Изменение адреса подключения с ключом требует явно заменить или очистить ключ. ID и тип провайдера неизменяемы.

## HTTP API

Все пути начинаются с `/api/llm`. Применяется существующая проверка прямого localhost-доступа, Host/Origin и forwarded-заголовков.

| Метод | Путь | Назначение |
| --- | --- | --- |
| GET / POST | `/providers` | Получить список / создать подключение |
| GET / PATCH / DELETE | `/providers/{id}` | Получить / изменить / удалить подключение |
| GET | `/providers/{id}/models` | Получить модели через официальный SDK |
| POST | `/providers/{id}/check` | Проверить связь запросом моделей, без генерации |
| GET / PUT | `/active` | Получить / выбрать активного провайдера и модель |

Пример создания локального подключения:

```json
{
  "id": "local",
  "kind": "ollama",
  "name": "Ollama на этом компьютере",
  "base_url": "http://127.0.0.1:11434",
  "timeout": 60,
  "connect_timeout": 10
}
```

OpenAI использует `kind: "openai"`, обычно `base_url: "https://api.openai.com/v1"` и входное поле api_key. Оно принимается только на запись и не возвращается в ответах, включая ошибки валидации. Публичные ответы не содержат secret_ref. Ключи не записываются в SQLite или логи приложения. Keyring использует защищённое хранилище ОС (на Windows — Credential Manager); при отсутствии поддерживаемого backend нет перехода к открытому файлу. Перенос SQLite на другой компьютер не переносит ключи — потребуется ввести их заново.

Выбор модели:

```json
{"provider_id": "local", "model": "qwen3:8b"}
```

Проверка списка моделей подтверждает доступ к этому endpoint, но не обещает, что любая модель поддерживает генерацию, инструменты или streaming. `ModelInfo.tools_supported` и `streaming_supported` могут быть null (неизвестно). OllamaProvider.model_info(model) дополнительно читает capabilities через show; неподдерживаемые запросы не преобразуются в скрытые обходные сценарии.

## Python API

```python
from contextlib import aclosing
from backend.app.llm.schemas import GenerationRequest, Message

service = app.state.llm_providers
selection = await service.active()
if selection is None:
    raise ValueError("Сначала выберите модель")

request = GenerationRequest(
    selection=selection,
    messages=[Message(role="user", text="Привет!")],
)
async with service.provider(selection.provider_id) as provider:
    response = await provider.generate(request)
    print(response.message.text)

async with service.provider(selection.provider_id) as provider:
    async with aclosing(provider.stream(request)) as stream:
        async for event in stream:
            if event.type == "text_delta":
                print(event.text, end="")
            elif event.type == "completed":
                final_response = event.response
```

Поток возвращает text_delta, завершённые tool_call и единственный completed с полным ModelResponse. Частичные JSON-аргументы не выдаются как готовые вызовы. Окончательный ответ — источник истины: в нём текст, вызовы, usage, finish_reason, warnings и continuation. При сетевом обрыве, ошибке или отмене completed не гарантирован; частичный текст нельзя считать завершённым ответом.

Timeout задаёт тайм-аут сетевых операций SDK, включая чтение очередного блока потока, а не суммарное время генерации. При необходимости вызывающий код может ограничить всю операцию через asyncio.timeout. Автоматические повторы отключены. В адаптере операции сериализованы; aclose ждёт активную операцию и закрывает HTTP-клиент. Поток необходимо полностью прочитать либо закрыть через aclosing, особенно при break или отмене.

Сервис создаёт адаптер на время `async with service.provider(...)` и закрывает его при выходе. Пула долгоживущих клиентов пока нет. Настройки копируются перед запросом: редактирование влияет на последующие обращения и не обрывает текущие. SQL-сессии закрываются до обращения к системному хранилищу и сети. Shutdown запрещает новые обращения, отменяет активные задачи с корректным выходом из их контекстов и дожидается изменений настроек. Настройки рассчитаны на один процесс приложения.

Официальный Ollama SDK 0.6.3 не предоставляет public aclose: обращение к `_client.aclose()` изолировано в одном методе адаптера и покрыто тестами. При обновлении SDK этот метод следует проверить.

## Продолжение после вызова инструмента

ToolDefinition содержит имя функции, описание и JSON Schema параметров. Для OpenAI используется `strict=false`: адаптер не переписывает схемы и не добавляет обязательные поля. Валидация аргументов и разрешение на выполнение — будущая ответственность AgentRunner/ToolExecutor.

```python
call = response.message.tool_calls[0]
# Выполнение инструментов здесь намеренно отсутствует.
followup_messages = [
    *request.messages,
    response.message,
    Message(role="tool", tool_call_id=call.id, text="Результат инструмента"),
]
```

Следует передавать **целый** `response.message`, а не пересоздавать его только из text. Continuation хранит данные провайдера:

- OpenAI: output items, исходные call_id, reasoning items и encrypted_content; запросы используют store=false и не зависят от серверного previous_response_id.
- Ollama: накопленное сообщение с thinking и tool_calls. Сгенерированный внутренний ID стабилен между tool_call и completed. Ollama 0.6.3 передаёт результат по tool_name, поэтому результаты нескольких вызовов необходимо возвращать в исходном порядке; обратный порядок отклоняется.

Continuation привязан к ID провайдера, его типу, адресу и модели. Смешивание отклоняется до сетевого запроса. Это транспортные данные для backend, а не инструкции для модели и не публичные данные UI. Raw reasoning/thinking не выводятся автоматически в поток пользовательского текста.

ToolCall сохраняет arguments_json даже при некорректном JSON; arguments() разбирает только JSON-объект и может выбросить ValueError. При повреждённых аргументах ответ содержит предупреждение. При finish_reason=length/other и предупреждении об incomplete нельзя считать tool calls готовыми к исполнению без отдельной проверки.

## Ошибки и диагностика

ProviderError различает timeout, connection_error, authentication, rate_limit, not_found, invalid_request, unsupported, protocol_error, server_error и closed. Исходные тексты SDK не возвращаются. CancelledError распространяется как отмена, не превращается в успешный частичный ответ. Ошибки keyring выделены отдельно. Если настройки уже сохранены, но очистка старого ключа ОС не удалась, credential_cleanup явно сообщает об этом; следует проверить системное хранилище.

HTTP API возвращает безопасный detail с code, message и upstream_status. Неизвестная запись — 404, конфликт ID — 409, некорректные параметры — 422, rate limit — 429, тайм-аут — 504, недоступное хранилище/закрытие — 503, прочие upstream-ошибки — 502.

```powershell
python -m scripts.check_llm --provider ollama
python -m scripts.check_llm --provider ollama --model qwen3:8b --generate --stream
python -m scripts.check_llm --provider openai
```

Для OpenAI диагностический скрипт читает FOLLIANT_LLM_API_KEY или OPENAI_API_KEY из окружения; не передавайте секрет аргументом командной строки. Для альтернативного адреса используйте --base-url. По умолчанию выполняется только list_models; --generate явно включает реальную генерацию, которая у облачного провайдера может быть платной. Скрипт не изменяет сохранённые настройки приложения и закрывает клиент в finally.

Тесты: `python -B -m unittest discover -s tests -v`. `test_llm.py` использует настоящие парсеры SDK и mock HTTP transports, без платных запросов и реального хранилища ключей. Проверяются текст, SSE/NDJSON, tool calling, частичные аргументы, продолжение, порядок результатов, ошибки, отмена, cleanup клиентов, SQL persistence и отсутствие ключей в API/SQLite.

Официальные источники: [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling), [OpenAI streaming](https://developers.openai.com/api/docs/guides/streaming-responses), [Ollama tool calling](https://docs.ollama.com/capabilities/tool-calling), [Ollama streaming](https://docs.ollama.com/capabilities/streaming).

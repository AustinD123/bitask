# Results

| case | model | one-shot visible | one-shot hidden | loop visible | loop hidden | avg attempts |
|---|---|---|---|---|---|---|
| 01_heap_overflow | openai/gpt-oss-20b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |
| 01_heap_overflow | openai/gpt-oss-120b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |
| 02_signed_overflow | openai/gpt-oss-20b | 2/2 | 1/2 | 2/2 | 1/2 | 1.0 |
| 02_signed_overflow | openai/gpt-oss-120b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |
| 03_iterator_invalidation | openai/gpt-oss-20b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |
| 03_iterator_invalidation | openai/gpt-oss-120b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |
| 04_data_race | openai/gpt-oss-20b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |
| 04_data_race | openai/gpt-oss-120b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |
| 05_use_after_free | openai/gpt-oss-20b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |
| 05_use_after_free | openai/gpt-oss-120b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |
| 06_double_free | openai/gpt-oss-20b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |
| 06_double_free | openai/gpt-oss-120b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |
| 07_off_by_one | openai/gpt-oss-20b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |
| 07_off_by_one | openai/gpt-oss-120b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |
| 08_memory_leak | openai/gpt-oss-20b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |
| 08_memory_leak | openai/gpt-oss-120b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |
| 09_null_deref | openai/gpt-oss-20b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |
| 09_null_deref | openai/gpt-oss-120b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |
| 10_uninitialised_read | openai/gpt-oss-20b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |
| 10_uninitialised_read | openai/gpt-oss-120b | 2/2 | 2/2 | 2/2 | 2/2 | 1.0 |

## Overall pass rates

| model | one-shot visible | one-shot hidden | loop visible | loop hidden |
|---|---|---|---|---|
| openai/gpt-oss-20b | 20/20 (100%) | 19/20 (95%) | 20/20 (100%) | 19/20 (95%) |
| openai/gpt-oss-120b | 20/20 (100%) | 20/20 (100%) | 20/20 (100%) | 20/20 (100%) |

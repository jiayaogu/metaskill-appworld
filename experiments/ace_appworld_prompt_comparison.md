| Change | ACE line or range | AppWorld v0.1.3 line | Added example lines |
| --- | --- | --- | ---: |
| Extract the Spotify password by matching `account_name` | [162](/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/prompts/appworld_react_generator_prompt.txt:162) | [165](https://github.com/StonyBrookNLP/appworld/blob/v0.1.3/experiments/prompts/react.txt#L165) | — |
| Save `spotify_access_token` from the login response | [182](/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/prompts/appworld_react_generator_prompt.txt:182) | No assignment; first used at [287](https://github.com/StonyBrookNLP/appworld/blob/v0.1.3/experiments/prompts/react.txt#L287) | — |
| Loop through pages until the API returns an empty page | [220](/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/prompts/appworld_react_generator_prompt.txt:220) | Fixed `page_index < 10` limit at [286](https://github.com/StonyBrookNLP/appworld/blob/v0.1.3/experiments/prompts/react.txt#L286) | — |
| Added most-liked-song example | [253–515](/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/prompts/appworld_react_generator_prompt.txt:253) | Absent | 263 |
| Added Phone/Simple Note example | [517–945](/home/jiayao/Metaskill-library/baselines/ace/ace-appworld/experiments/prompts/appworld_react_generator_prompt.txt:517) | Absent | 429 |
| **Two added examples, total** | — | Absent | **692** |
| **Complete prompt comparison** | ACE: 972 lines; 781 added, 152 removed | AppWorld: 343 lines; net change: +629 lines | **692 of 781 added lines (88.6%)** |

# Third-party code

These libraries are bundled unchanged in `web/vendor/`. All of them are under the MIT license (text below).

| Library | Version | Copyright | Where |
|---|---|---|---|
| [three.js](https://github.com/mrdoob/three.js) (+ addons: GLTFLoader, FBXLoader, BVHLoader, NURBS, BufferGeometryUtils) | r169 | © 2010–2024 three.js authors | `web/vendor/three/` |
| [three-vrm](https://github.com/pixiv/three-vrm) | 3.x | © 2019–2024 pixiv Inc. | `web/vendor/three/three-vrm.module.min.js` |
| [fflate](https://github.com/101arrowz/fflate) | 0.8.2 | © 2023 Arjun Barrett | `web/vendor/three/addons/libs/fflate.module.js` |
| [KaTeX](https://github.com/KaTeX/KaTeX) | 0.16 | © 2013–2020 Khan Academy and other contributors | `web/vendor/katex/` |
| [Drawflow](https://github.com/jerosoler/Drawflow) | 0.0.x | © 2020 Jero Soler | `web/vendor/drawflow.min.*` |

## MIT License

```
Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## Models

Models are not part of this repository; they are downloaded at run time and keep their own licenses: the Ollama models
you pull, faster-whisper / Whisper (MIT), Piper and its voices (each voice has its own license — see its model card),
Vosk models (Apache-2.0), OmniVoice, YuNet face detection (MIT, OpenCV Zoo), Stable Diffusion XL inpainting
(CreativeML Open RAIL++-M).

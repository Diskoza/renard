"""Runs INSIDE data/voiceclone/venv (torch cu128 + piper-tts[train]): fine-tunes a Piper voice.
    python voicebake_train.py <progress.json> fit --data.… --model.… --trainer.…
    python voicebake_train.py <progress.json> export <checkpoint> <out.onnx>
Windows has no compiler for Piper's Cython «monotonic_align»: the same algorithm is provided with numba."""
import json
import sys
import time
import types


def _numba_monotonic_align():
    import numba
    import numpy as np

    @numba.njit(cache=True)
    def _one(path, value, t_y, t_x, max_neg_val=-1e9):
        index = t_x - 1
        for y in range(t_y):
            for x in range(max(0, t_x + y - t_y), min(t_x, y + 1)):
                v_cur = max_neg_val if x == y else value[y - 1, x]
                if x == 0:
                    v_prev = 0.0 if y == 0 else max_neg_val
                else:
                    v_prev = value[y - 1, x - 1]
                value[y, x] += max(v_prev, v_cur)
        for y in range(t_y - 1, -1, -1):
            path[y, index] = 1
            if index != 0 and (index == y or value[y - 1, index] < value[y - 1, index - 1]):
                index -= 1

    @numba.njit(cache=True, parallel=True)
    def maximum_path_c(paths, values, t_ys, t_xs):
        for i in numba.prange(paths.shape[0]):
            _one(paths[i], values[i], t_ys[i], t_xs[i])

    mod = types.ModuleType("piper.train.vits.monotonic_align.monotonic_align.core")
    mod.maximum_path_c = maximum_path_c
    pkg = types.ModuleType("piper.train.vits.monotonic_align.monotonic_align")
    pkg.core = mod
    pkg.__path__ = []
    sys.modules[pkg.__name__] = pkg
    sys.modules[mod.__name__] = mod
    _ = np


def _old_piper_aliases():
    """Checkpoints from rhasspy/piper-checkpoints were pickled with the old package name «piper_train»."""
    import importlib
    for old, new in [("piper_train", "piper.train"), ("piper_train.vits", "piper.train.vits")]:
        try:
            sys.modules.setdefault(old, importlib.import_module(new))
        except Exception:
            pass
    for sub in ("lightning", "dataset", "models", "commons", "config"):
        try:
            sys.modules.setdefault(f"piper_train.vits.{sub}", importlib.import_module(f"piper.train.vits.{sub}"))
        except Exception:
            pass


def main():
    progress, cmd = sys.argv[1], sys.argv[2]
    import logging
    logging.basicConfig(level=logging.INFO)
    _numba_monotonic_align()

    def write(**kw):
        try:
            with open(progress, "w", encoding="utf-8") as f:
                json.dump({**kw, "ts": time.time()}, f)
        except OSError:
            pass

    if cmd == "export":
        sys.argv = ["export_onnx", "--checkpoint", sys.argv[3], "--output-file", sys.argv[4]]
        from piper.train.export_onnx import main as export_main
        export_main()
        write(stage="exported")
        return

    import lightning as L
    from piper.train.__main__ import VitsLightningCLI, _DEFAULT_CALLBACKS
    from piper.train.vits.dataset import VitsDataModule
    from piper.train.vits.lightning import VitsModel
    import torch

    class Progress(L.Callback):
        last_save = time.time()

        def on_train_batch_end(self, trainer, pl_module, outputs, batch, batch_idx):
            nb = max(1, int(trainer.num_training_batches))
            step = trainer.current_epoch * nb + batch_idx + 1
            if time.time() - self.last_save > 300 and trainer.checkpoint_callback is not None:
                import os
                trainer.save_checkpoint(os.path.join(trainer.checkpoint_callback.dirpath, "last.ckpt"))
                self.last_save = time.time()
            if step % 5 == 0 or batch_idx == nb - 1:
                logs = {k: float(v) for k, v in trainer.callback_metrics.items() if k in ("loss_gen_all", "loss_disc_all", "val_mel")}
                write(stage="train", epoch=trainer.current_epoch, step=step, total=trainer.max_epochs * nb, **logs)

    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    sys.argv = ["piper.train"] + sys.argv[2:]
    write(stage="train", epoch=0, step=0, total=1)
    from lightning.pytorch.callbacks import ModelCheckpoint
    keep = [ModelCheckpoint(save_top_k=0, save_last=True, every_n_train_steps=200, save_on_train_epoch_end=True)]
    _ = _DEFAULT_CALLBACKS
    VitsLightningCLI(VitsModel, VitsDataModule,
                     trainer_defaults={"max_epochs": -1, "callbacks": keep + [Progress()]})
    write(stage="trained")


if __name__ == "__main__":
    main()

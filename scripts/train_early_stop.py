#!/usr/bin/env python3
"""
Early-stopping wrapper for mlx_lm.lora.

Launches training as a subprocess, watches stdout for val loss lines,
stops when val loss hasn't improved for PATIENCE consecutive evals,
and prints the best checkpoint path so 07_fuse.sh can pick it up.

Usage (called by 06_train.sh):
  python3 train_early_stop.py --config runtime_lora.yaml --patience 3 --save-every 100
"""
import argparse, os, re, signal, subprocess, sys

PATIENCE_DEFAULT = 3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config',     required=True)
    parser.add_argument('--patience',   type=int, default=PATIENCE_DEFAULT)
    parser.add_argument('--save-every', type=int, default=100,
                        help='Must match save_every in lora_config.yaml')
    args = parser.parse_args()

    best_val   = float('inf')
    no_improve = 0
    best_iter  = 0
    adapter_dir = None

    # Read adapter_path from config
    for line in open(args.config):
        if line.strip().startswith('adapter_path'):
            adapter_dir = line.split(':', 1)[1].strip()
            break
    if not adapter_dir:
        adapter_dir = './adapters'

    cmd = ['mlx_lm.lora', '--config', args.config]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)

    val_re = re.compile(r'Iter\s+(\d+).*Val loss\s+([\d.]+)')

    print(f"[early_stop] patience={args.patience} | adapter_dir={adapter_dir}")
    sys.stdout.flush()

    try:
        for line in proc.stdout:
            print(line, end='', flush=True)
            m = val_re.search(line)
            if not m:
                continue
            it, val = int(m.group(1)), float(m.group(2))
            if val < best_val:
                best_val   = val
                best_iter  = it
                no_improve = 0
                print(f"[early_stop] ✓ new best val={best_val:.4f} @ iter {best_iter}", flush=True)
            else:
                no_improve += 1
                print(f"[early_stop] no improvement {no_improve}/{args.patience} "
                      f"(best={best_val:.4f} @ iter {best_iter})", flush=True)
                if no_improve >= args.patience:
                    print(f"[early_stop] patience exceeded — stopping training", flush=True)
                    proc.send_signal(signal.SIGTERM)
                    break
    finally:
        proc.wait()

    # Find the closest saved checkpoint to best_iter
    best_ckpt = None
    if os.path.isdir(adapter_dir):
        ckpts = sorted([
            f for f in os.listdir(adapter_dir)
            if re.match(r'\d{7}_adapters\.safetensors', f)
        ])
        # Pick the checkpoint at or just before best_iter
        target = f"{best_iter:07d}_adapters.safetensors"
        candidates = [c for c in ckpts if c <= target]
        if candidates:
            best_ckpt = os.path.join(adapter_dir, candidates[-1])

    if best_ckpt and os.path.exists(best_ckpt):
        # Copy best checkpoint to adapters.safetensors so fuse uses it
        import shutil
        final = os.path.join(adapter_dir, 'adapters.safetensors')
        shutil.copy2(best_ckpt, final)
        print(f"[early_stop] best checkpoint → {best_ckpt} (val={best_val:.4f} @ iter {best_iter})")
        print(f"[early_stop] copied to {final} for fusing")
    else:
        print(f"[early_stop] best iter={best_iter} val={best_val:.4f} "
              f"(no matching checkpoint found — using final adapter)")

    print(f"[early_stop] done. best_val={best_val:.4f} best_iter={best_iter}")


if __name__ == '__main__':
    main()

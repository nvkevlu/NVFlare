# Copyright (c) 2026, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Small real-Cell smoke for the negotiated one-port native tensor bulk path."""

import argparse
import threading
import time
from pathlib import Path

import torch

from dev_tools.f3.cellnet_bench import RX_FQCN, TX_FQCN, configure_f3, resolve_cell_security
from nvflare.apis.fl_constant import ConnectionSecurity
from nvflare.app_opt.pt.tensor_downloader import TensorDownloadable, download_tensors
from nvflare.fuel.f3.cellnet.cell import Cell
from nvflare.fuel.f3.streaming.obj_downloader import ObjectDownloader


def run_receiver(url: str, credentials_dir: Path):
    secure, credentials = resolve_cell_security(RX_FQCN, url, ConnectionSecurity.MTLS, credentials_dir)
    cell = Cell(RX_FQCN, url, secure=secure, credentials=credentials)
    downloader = ObjectDownloader(cell, timeout=300, num_receivers=1, receiver_ids=[TX_FQCN])
    tensors = {f"tensor_{index}": torch.full((1024 * 1024,), float(index)) for index in range(6)}
    ref_id = downloader.add_object(TensorDownloadable(tensors, max_chunk_size=2 * 1024 * 1024))
    cell.start()
    print(f"READY {ref_id}", flush=True)
    try:
        time.sleep(300)
    except KeyboardInterrupt:
        pass
    finally:
        cell.stop()


def run_sender(url: str, credentials_dir: Path, ref_id: str):
    secure, credentials = resolve_cell_security(TX_FQCN, url, ConnectionSecurity.MTLS, credentials_dir)
    connected = threading.Event()
    cell = Cell(TX_FQCN, url, secure=secure, credentials=credentials)
    cell.set_cell_connected_cb(lambda _agent: connected.set())
    cell.start()
    try:
        if not connected.wait(30):
            raise RuntimeError("sender did not connect")
        error, result = download_tensors(RX_FQCN, ref_id, 60, cell)
        if error:
            raise RuntimeError(error)
        if set(result) != {f"tensor_{index}" for index in range(6)}:
            raise RuntimeError("unexpected tensor keys")
        for index in range(6):
            if not torch.all(result[f"tensor_{index}"] == index):
                raise RuntimeError(f"tensor_{index} content mismatch")
        print("RESULT OK native_bulk tensors=6 bytes=25165824", flush=True)
    finally:
        cell.stop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("recv", "send"))
    parser.add_argument("--url", required=True)
    parser.add_argument("--credentials-dir", type=Path, required=True)
    parser.add_argument("--f3-config", required=True)
    parser.add_argument("--ref-id")
    args = parser.parse_args()
    configure_f3(args.f3_config)
    if args.role == "recv":
        run_receiver(args.url, args.credentials_dir)
    else:
        if not args.ref_id:
            parser.error("send requires --ref-id")
        run_sender(args.url, args.credentials_dir, args.ref_id)


if __name__ == "__main__":
    main()

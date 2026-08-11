# Copyright (c) 2023, NVIDIA CORPORATION.  All rights reserved.
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
from unittest.mock import MagicMock

import pytest

from nvflare.apis.fl_constant import ConnectionSecurity
from nvflare.fuel.f3.comm_error import CommError
from nvflare.fuel.f3.drivers import net_utils
from nvflare.fuel.f3.drivers.driver_params import DriverParams
from nvflare.fuel.f3.drivers.net_utils import encode_url, parse_url


class TestNetUtils:
    def test_encode_url(self):

        params = {
            DriverParams.SCHEME.value: "tcp",
            DriverParams.HOST.value: "flare.test.com",
            DriverParams.PORT.value: 1234,
            "b": "test value",
            "a": 123,
            "r": False,
        }

        url = encode_url(params)
        assert url == "tcp://flare.test.com:1234?b=test+value&a=123&r=False"

    def test_parse_url(self):
        url = "grpc://test.com:8002?a=123&b=test"
        params = parse_url(url)
        assert params.get(DriverParams.URL) == url
        assert int(params.get(DriverParams.PORT)) == 8002
        assert params.get("a") == "123"
        assert params.get("b") == "test"

    @pytest.mark.parametrize("value", [True, "true", "YES"])
    def test_client_ssl_context_can_enable_hostname_verification(self, monkeypatch, value):
        context = MagicMock()
        monkeypatch.setattr(net_utils.ssl, "create_default_context", lambda _purpose: context)

        result = net_utils.get_ssl_context(
            {
                DriverParams.SCHEME.value: "stcp",
                DriverParams.CONNECTION_SECURITY.value: ConnectionSecurity.TLS,
                DriverParams.CA_CERT.value: "/credentials/rootCA.pem",
                DriverParams.VERIFY_HOSTNAME.value: value,
            },
            ssl_server=False,
        )

        assert result is context
        assert context.check_hostname is True
        context.load_verify_locations.assert_called_once_with("/credentials/rootCA.pem")

    def test_client_ssl_context_preserves_legacy_hostname_default(self, monkeypatch):
        context = MagicMock()
        monkeypatch.setattr(net_utils.ssl, "create_default_context", lambda _purpose: context)

        net_utils.get_ssl_context(
            {
                DriverParams.SCHEME.value: "stcp",
                DriverParams.CONNECTION_SECURITY.value: ConnectionSecurity.TLS,
                DriverParams.CA_CERT.value: "/credentials/rootCA.pem",
            },
            ssl_server=False,
        )

        assert context.check_hostname is False

    @pytest.mark.parametrize("value", ["invalid", 1, None])
    def test_client_ssl_context_rejects_invalid_hostname_verification(self, monkeypatch, value):
        context = MagicMock()
        monkeypatch.setattr(net_utils.ssl, "create_default_context", lambda _purpose: context)

        with pytest.raises(CommError, match="verify_hostname must be a bool or boolean string") as exc_info:
            net_utils.get_ssl_context(
                {
                    DriverParams.SCHEME.value: "stcp",
                    DriverParams.CONNECTION_SECURITY.value: ConnectionSecurity.TLS,
                    DriverParams.CA_CERT.value: "/credentials/rootCA.pem",
                    DriverParams.VERIFY_HOSTNAME.value: value,
                },
                ssl_server=False,
            )
        assert exc_info.value.code == CommError.BAD_CONFIG

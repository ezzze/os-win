# Copyright 2015 Cloudbase Solutions Srl
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import ddt
import mock

from os_win import exceptions
from os_win.tests import test_base
from os_win.utils.storage import smbutils


@ddt.ddt
class SMBUtilsTestCase(test_base.OsWinBaseTestCase):
    def setUp(self):
        super(SMBUtilsTestCase, self).setUp()

        self._smbutils = smbutils.SMBUtils()
        self._smbutils._win32_utils = mock.Mock()
        self._smbutils._smb_conn = mock.Mock()
        self._mock_run = self._smbutils._win32_utils.run_and_check_output
        self._smb_conn = self._smbutils._smb_conn

    @mock.patch.object(smbutils.SMBUtils, 'unmount_smb_share')
    @mock.patch('os.path.exists')
    def _test_check_smb_mapping(self, mock_exists, mock_unmount_smb_share,
                                existing_mappings=True, share_available=False):
        mock_exists.return_value = share_available

        fake_mappings = (
            [mock.sentinel.smb_mapping] if existing_mappings else [])

        self._smb_conn.Msft_SmbMapping.return_value = fake_mappings

        ret_val = self._smbutils.check_smb_mapping(
            mock.sentinel.share_path, remove_unavailable_mapping=True)

        self.assertEqual(existing_mappings and share_available, ret_val)
        if existing_mappings and not share_available:
            mock_unmount_smb_share.assert_called_once_with(
                mock.sentinel.share_path, force=True)

    def test_check_mapping(self):
        self._test_check_smb_mapping()

    def test_remake_unavailable_mapping(self):
        self._test_check_smb_mapping(existing_mappings=True,
                                     share_available=False)

    def test_available_mapping(self):
        self._test_check_smb_mapping(existing_mappings=True,
                                     share_available=True)

    def test_mount_smb_share(self):
        fake_create = self._smb_conn.Msft_SmbMapping.Create
        self._smbutils.mount_smb_share(mock.sentinel.share_path,
                                       mock.sentinel.username,
                                       mock.sentinel.password)
        fake_create.assert_called_once_with(
            RemotePath=mock.sentinel.share_path,
            UserName=mock.sentinel.username,
            Password=mock.sentinel.password)

    @mock.patch.object(smbutils, 'wmi', create=True)
    def test_mount_smb_share_failed(self, mock_wmi):
        mock_wmi.x_wmi = Exception
        self._smb_conn.Msft_SmbMapping.Create.side_effect = mock_wmi.x_wmi

        self.assertRaises(exceptions.SMBException,
                          self._smbutils.mount_smb_share,
                          mock.sentinel.share_path)

    def _test_unmount_smb_share(self, force=False):
        fake_mapping = mock.Mock()
        fake_mapping_attr_err = mock.Mock()
        fake_mapping_attr_err.side_effect = AttributeError
        smb_mapping_class = self._smb_conn.Msft_SmbMapping
        smb_mapping_class.return_value = [fake_mapping, fake_mapping_attr_err]

        self._smbutils.unmount_smb_share(mock.sentinel.share_path,
                                          force)

        smb_mapping_class.assert_called_once_with(
            RemotePath=mock.sentinel.share_path)
        fake_mapping.Remove.assert_called_once_with(Force=force)

    def test_soft_unmount_smb_share(self):
        self._test_unmount_smb_share()

    def test_force_unmount_smb_share(self):
        self._test_unmount_smb_share(force=True)

    @mock.patch.object(smbutils, 'wmi', create=True)
    def test_unmount_smb_share_wmi_exception(self, mock_wmi):
        mock_wmi.x_wmi = Exception
        fake_mapping = mock.Mock()
        fake_mapping.Remove.side_effect = mock_wmi.x_wmi
        self._smb_conn.Msft_SmbMapping.return_value = [fake_mapping]

        self.assertRaises(mock_wmi.x_wmi, self._smbutils.unmount_smb_share,
                          mock.sentinel.share_path, force=True)

    @mock.patch.object(smbutils, 'ctypes')
    @mock.patch.object(smbutils, 'kernel32', create=True)
    @mock.patch('os.path.abspath')
    def _test_get_share_capacity_info(self, mock_abspath,
                                      mock_kernel32, mock_ctypes,
                                      raised_exc=None, ignore_errors=False):
        expected_values = ('total_bytes', 'free_bytes')

        mock_params = [mock.Mock(value=value) for value in expected_values]
        mock_ctypes.c_ulonglong.side_effect = mock_params
        mock_ctypes.c_wchar_p = lambda x: (x, 'c_wchar_p')

        self._mock_run.side_effect = raised_exc(
            func_name='fake_func_name',
            error_code='fake_error_code',
            error_message='fake_error_message') if raised_exc else None

        if raised_exc and not ignore_errors:
            self.assertRaises(raised_exc,
                              self._smbutils.get_share_capacity_info,
                              mock.sentinel.share_path,
                              ignore_errors=ignore_errors)
        else:
            ret_val = self._smbutils.get_share_capacity_info(
                mock.sentinel.share_path,
                ignore_errors=ignore_errors)
            expected_ret_val = (0, 0) if raised_exc else expected_values

            self.assertEqual(expected_ret_val, ret_val)

        mock_abspath.assert_called_once_with(mock.sentinel.share_path)
        mock_ctypes.pointer.assert_has_calls(
            [mock.call(param) for param in mock_params])
        self._mock_run.assert_called_once_with(
            mock_kernel32.GetDiskFreeSpaceExW,
            mock_ctypes.c_wchar_p(mock_abspath.return_value),
            None,
            mock_ctypes.pointer.return_value,
            mock_ctypes.pointer.return_value,
            kernel32_lib_func=True)

    def test_get_share_capacity_info_successfully(self):
        self._test_get_share_capacity_info()

    def test_get_share_capacity_info_ignored_error(self):
        self._test_get_share_capacity_info(
            raised_exc=exceptions.Win32Exception,
            ignore_errors=True)

    def test_get_share_capacity_info_raised_exc(self):
        self._test_get_share_capacity_info(
            raised_exc=exceptions.Win32Exception)

    def test_get_smb_share_path(self):
        fake_share = mock.Mock(Path=mock.sentinel.share_path)
        self._smb_conn.Msft_SmbShare.return_value = [fake_share]

        share_path = self._smbutils.get_smb_share_path(
            mock.sentinel.share_name)

        self.assertEqual(mock.sentinel.share_path, share_path)
        self._smb_conn.Msft_SmbShare.assert_called_once_with(
            Name=mock.sentinel.share_name)

    def test_get_unexisting_smb_share_path(self):
        self._smb_conn.Msft_SmbShare.return_value = []

        share_path = self._smbutils.get_smb_share_path(
            mock.sentinel.share_name)

        self.assertIsNone(share_path)
        self._smb_conn.Msft_SmbShare.assert_called_once_with(
            Name=mock.sentinel.share_name)

    @ddt.data({'local_ips': [mock.sentinel.ip0, mock.sentinel.ip1],
               'dest_ips': [mock.sentinel.ip2, mock.sentinel.ip3],
               'expected_local': False},
              {'local_ips': [mock.sentinel.ip0, mock.sentinel.ip1],
               'dest_ips': [mock.sentinel.ip1, mock.sentinel.ip3],
               'expected_local': True})
    @ddt.unpack
    @mock.patch('os_win._utils.get_ips')
    @mock.patch('socket.gethostname')
    def test_is_local_share(self, mock_gethostname, mock_get_ips,
                            local_ips, dest_ips, expected_local):
        fake_share_server = 'fake_share_server'
        fake_share = '\\\\%s\\fake_share' % fake_share_server
        mock_get_ips.side_effect = (local_ips, dest_ips)
        self._smbutils._loopback_share_map = {}

        is_local = self._smbutils.is_local_share(fake_share)
        self.assertEqual(expected_local, is_local)

        # We ensure that this value is cached, calling it again
        # and making sure that we have attempted to resolve the
        # address only once.
        self._smbutils.is_local_share(fake_share)

        mock_gethostname.assert_called_once_with()
        mock_get_ips.assert_has_calls(
            [mock.call(mock_gethostname.return_value),
             mock.call(fake_share_server)])

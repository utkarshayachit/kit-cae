# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import omni.ext
from omni.cae.pipapi import pip_install


class Extension(omni.ext.IExt):
    def on_startup(self, _ext_id):
        import omni.kit.tool.asset_importer as ai

        if pip_install(package="h5py", version="3.13", module="h5py", required=True):

            from .importer import EDEMImporter

            self._importer = EDEMImporter()
            ai.register_importer(self._importer)
        else:
            self._importer = None

    def on_shutdown(self):
        import omni.kit.tool.asset_importer as ai

        if self._importer is not None:
            ai.remove_importer(self._importer)
            self._importer = None

# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
#  its affiliates is strictly prohibited.

import asyncio
from logging import getLogger

import omni.kit.commands
from omni.cae.material_library import get_cae_materials
from omni.kit.async_engine import run_coroutine
from omni.usd import duplicate_prim, get_context
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

logger = getLogger(__name__)


def get_default_width():
    # from carb.settings import get_settings

    # w = get_settings().get_as_float("/persistent/rtx/hydra/points/defaultWidth")
    # return w if w > 0.0 else 0.1
    # we no longer use the settings to get the default width as users often forget to set it
    # causing issues with large point clouds.
    return 0.001  # default width for points


def create_material(mtl_name: str, stage: Usd.Stage, path: Sdf.Path) -> Usd.Prim:
    omni.kit.commands.execute(
        "CreateMdlMaterialPrim", mtl_name=mtl_name, mtl_url=get_cae_materials(), mtl_path=str(path), stage=stage
    )
    return stage.GetPrimAtPath(path)


def bind_material(prim: Usd.Prim, material: Usd.Prim):
    omni.kit.commands.execute(
        "BindMaterial",
        prim_path=str(prim.GetPath()),
        material_path=str(material.GetPath()),
        strength=UsdShade.Tokens.weakerThanDescendants,
    )


class CreateCaeAlgorithmsExtractBoundingBox(omni.kit.commands.Command):
    def __init__(self, dataset_paths: list[str], prim_path: str):
        self._dataset_paths = dataset_paths
        self._prim_path = prim_path

    def do(self):
        logger.info("executing  CreateCaeAlgorithmsExtractBoundingBox.do()")
        stage: Usd.Stage = get_context().get_stage()

        dataset_prims = []
        for dataset_path in self._dataset_paths:
            dataset_prim = stage.GetPrimAtPath(dataset_path)
            if not dataset_prim:
                raise RuntimeError("DataSet prim is invalid!")
            dataset_prims.append(dataset_prim)

        if not dataset_prims:
            raise RuntimeError("No DataSet prims found!")

        primT: UsdGeom.BasisCurves = UsdGeom.BasisCurves.Define(stage, self._prim_path)

        # apply "Points" schema
        prim = primT.GetPrim()
        prim.AddAppliedSchema("CaeAlgorithmsBoundingBoxAPI")
        ns = "omni:cae:algorithms:boundingBox"
        prim.CreateRelationship(f"{ns}:datasets", custom=False).SetTargets({t.GetPath() for t in dataset_prims})
        prim.CreateAttribute(f"{ns}:width", Sdf.ValueTypeNames.Float, custom=False).Set(0.1)

        # setup basis curve
        # need to populate points otherwise the curve doesn't render when we update it the first time.
        # primT.CreatePointsAttr().Set([(0, 0, 0), (0.1, 0, 0), (0.2, 0, 0), (0.3, 0, 0)])
        # primT.CreateCurveVertexCountsAttr().Set([4])
        # primT.CreateExtentAttr().Set([(0.0, 0.0, 0.0), (0.3, 0.05, 0.05)])
        primT.CreateWidthsAttr().Set([(0.1)])
        primT.CreateTypeAttr().Set(UsdGeom.Tokens.linear)
        primT.SetWidthsInterpolation(UsdGeom.Tokens.constant)
        primT.CreateWrapAttr().Set(UsdGeom.Tokens.nonperiodic)

        logger.info("created '%s''", str(prim.GetPath()))


class CreateCaeAlgorithmsExtractPoints(omni.kit.commands.Command):
    def __init__(self, dataset_path: str, prim_path: str):
        self._dataset_path = dataset_path
        self._prim_path = prim_path

    def do(self):
        logger.info("executing  CreateCaeAlgorithmsExtractPoints.do()")
        stage: Usd.Stage = get_context().get_stage()
        dataset_prim = stage.GetPrimAtPath(self._dataset_path)
        if not dataset_prim:
            raise RuntimeError("DataSet prim is invalid!")

        primT = UsdGeom.Points.Define(stage, self._prim_path)

        default_width = get_default_width()
        # apply "Points" schema
        prim = primT.GetPrim()
        prim.AddAppliedSchema("CaeAlgorithmsPointsAPI")
        ns = "omni:cae:algorithms:points"
        prim.CreateRelationship(f"{ns}:dataset", custom=False).SetTargets({dataset_prim.GetPath()})
        prim.CreateRelationship(f"{ns}:colors", custom=False).SetTargets({})
        prim.CreateRelationship(f"{ns}:widths", custom=False).SetTargets({})
        prim.CreateAttribute(f"{ns}:width", Sdf.ValueTypeNames.Float, custom=False).Set(default_width)
        prim.CreateAttribute(f"{ns}:maxCount", Sdf.ValueTypeNames.Int, custom=False).Set(10000000)
        prim.CreateAttribute(f"{ns}:widthsRamp", Sdf.ValueTypeNames.Float2, custom=False).Set((0.5, 1.5))
        prim.CreateAttribute(f"{ns}:widthsDomain", Sdf.ValueTypeNames.Float2, custom=False).Set((0.0, -1.0))

        primT.CreatePointsAttr()

        pvAPI = UsdGeom.PrimvarsAPI(primT.GetPrim())
        pvAPI.CreatePrimvar("scalar", Sdf.ValueTypeNames.FloatArray, UsdGeom.Tokens.vertex).Set([0.0])
        pvAPI.CreatePrimvar("widths", Sdf.ValueTypeNames.FloatArray, UsdGeom.Tokens.vertex).Set([default_width])

        # setup material
        material = create_material(
            "ScalarColor", stage, primT.GetPath().AppendChild("Materials").AppendChild("ScalarColor")
        )
        bind_material(primT, material)

        logger.info("created '%s''", str(prim.GetPath()))

    def undo(self):
        if self._prim_path:
            stage: Usd.Stage = get_context().get_stage()
            stage.RemovePrim(self._prim_path)
            self._prim_path = None


class CreateCaeAlgorithmsGlyphs(omni.kit.commands.Command):
    ns = "omni:cae:algorithms:glyphs"

    def __init__(self, dataset_path: str, prim_path: str):
        self._dataset_path = dataset_path
        self._prim_path = prim_path

    async def do(self):
        logger.info("executing  CreateCaeAlgorithmsGlyphs.do()")
        stage: Usd.Stage = get_context().get_stage()
        dataset_prim = stage.GetPrimAtPath(self._dataset_path)
        if not dataset_prim:
            raise RuntimeError("DataSet prim is invalid!")

        primT = UsdGeom.PointInstancer.Define(stage, self._prim_path)
        prim = primT.GetPrim()
        self.init_prim(prim)
        prim.CreateRelationship(f"{self.ns}:dataset", custom=False).SetTargets({dataset_prim.GetPath()})
        prim.CreateRelationship(f"{self.ns}:orientation", custom=False).SetTargets({})
        prim.CreateRelationship(f"{self.ns}:colors", custom=False).SetTargets({})
        prim.CreateRelationship(f"{self.ns}:scale", custom=False).SetTargets({})
        prim.CreateAttribute(f"{self.ns}:maxCount", Sdf.ValueTypeNames.Int, custom=False).Set(100000)

        # These attributes need to be created initially otherwise the renderer entirely skips the Prim even if we add
        # these properties later on in the Algorithm.
        primT.CreatePositionsAttr()
        primT.CreateProtoIndicesAttr([0])
        primT.CreateOrientationsAttr([])
        primT.CreateScalesAttr([])

        # api = UsdGeom.PrimvarsAPI(prim)
        # api.CreatePrimvar("scalar", Sdf.ValueTypeNames.FloatArray, UsdGeom.Tokens.vertex)

        # create prototypes under an "over" prim to skip the prototypes in standard stage navigation
        # refer to OpenUSD documentation for PointInstancer for more details.
        protosPrim = stage.OverridePrim(prim.GetPath().AppendChild("Protos"))
        # protosPrim = stage.DefinePrim(prim.GetPath().AppendChild("Protos"))

        prototypes = self.create_prototypes(stage, protosPrim.GetPath())
        primT.CreatePrototypesRel().SetTargets(prototypes)

        # create materials(s) for the glyphs
        material = create_material(
            "ScalarColor", stage, primT.GetPath().AppendChild("Materials").AppendChild("ScalarColor")
        )
        bind_material(primT, material)

        logger.info("created '%s' with %d prototypes", str(prim.GetPath()), len(prototypes))

    def init_prim(self, prim: Usd.Prim):
        prim.AddAppliedSchema("CaeAlgorithmsGlyphsAPI")
        prim.CreateAttribute(f"{self.ns}:shape", Sdf.ValueTypeNames.Token, custom=False).Set("arrow")

    def create_prototypes(self, stage: Usd.Stage, parent_path: Sdf.Path) -> list[Sdf.Path]:
        arrowXform = UsdGeom.Xform.Define(stage, parent_path.AppendChild("ArrowXform"))
        arrowCylinder = UsdGeom.Cylinder.Define(stage, arrowXform.GetPath().AppendChild("Cylinder"))
        arrowCylinder.CreateHeightAttr().Set(0.5)
        arrowCylinder.CreateRadiusAttr().Set(0.15)
        arrowCylinder.CreateAxisAttr().Set(UsdGeom.Tokens.x)
        arrowCylinder.AddTranslateOp().Set((0.25, 0, 0))
        arrowCone = UsdGeom.Cone.Define(stage, arrowXform.GetPath().AppendChild("Cone"))
        arrowCone.CreateHeightAttr().Set(0.5)
        arrowCone.CreateRadiusAttr().Set(0.3)
        arrowCone.CreateAxisAttr().Set(UsdGeom.Tokens.x)
        arrowCone.AddTranslateOp().Set((0.75, 0, 0))

        coneXform = UsdGeom.Xform.Define(stage, parent_path.AppendChild("ConeXform"))
        cone = UsdGeom.Cone.Define(stage, coneXform.GetPath().AppendChild("Cone"))
        cone.CreateHeightAttr().Set(1.0)
        cone.CreateRadiusAttr().Set(0.5)
        cone.CreateAxisAttr().Set(UsdGeom.Tokens.x)

        # offset cone so that the base is at the origin.
        xformAPI = UsdGeom.XformCommonAPI(cone.GetPrim())
        xformAPI.SetTranslate([0.5, 0, 0])

        sphereXform = UsdGeom.Xform.Define(stage, parent_path.AppendChild("SphereXform"))
        sphere = UsdGeom.Sphere.Define(stage, sphereXform.GetPath().AppendChild("Sphere"))
        sphere.CreateRadiusAttr().Set(0.5)

        return [arrowXform.GetPath(), coneXform.GetPath(), sphereXform.GetPath()]


class CreateCaeAlgorithmsCustomGlyphs(CreateCaeAlgorithmsGlyphs):
    def __init__(self, dataset_path: str, prim_path: str):
        super().__init__(dataset_path, prim_path)
        self._prototype_path = None

    async def do(self):
        self._prototype_path = await self.get_prototype_path()
        return await super().do()

    def init_prim(self, prim: Usd.Prim):
        prim.AddAppliedSchema("CaeAlgorithmsCustomGlyphsAPI")

    def create_prototypes(self, stage, parent_path) -> list[Sdf.Path]:
        proto_prim = stage.GetPrimAtPath(self._prototype_path)
        if not proto_prim:
            raise RuntimeError(f"Prototype prim '{self._prototype_path}' is invalid!")

        clone_path = parent_path.AppendChild(proto_prim.GetName())
        duplicate_prim(stage, proto_prim.GetPath(), clone_path)
        logger.warning("cloned prototype to: %s", clone_path)
        return [clone_path]

    async def get_prototype_path(self) -> str:
        from omni.kit.property.usd import RelationshipTargetPicker

        stage: Usd.Stage = get_context().get_stage()
        picker = RelationshipTargetPicker(
            stage,
            [],
            None,
            {
                "model_window": True,
                "target_name": "Prototype",
                "target_plural_name": "Prototypes",
            },
        )

        loop = asyncio.get_event_loop()
        future = loop.create_future()
        picker.show(1, lambda paths: future.set_result(paths[0] if paths else None))
        path = await future
        logger.warning("selected prototype: %s", path)
        return path


class CreateCaeAlgorithmsExtractExternalFaces(omni.kit.commands.Command):
    def __init__(self, dataset_path: str, prim_path: str):
        self._dataset_path = dataset_path
        self._prim_path = prim_path

    def do(self):
        logger.info("executing %s.do()", self.__class__.__name__)
        stage: Usd.Stage = get_context().get_stage()
        dataset_prim = stage.GetPrimAtPath(self._dataset_path)
        if not dataset_prim:
            raise RuntimeError("DataSet prim is invalid!")

        primT = UsdGeom.Mesh.Define(stage, self._prim_path)
        prim = primT.GetPrim()
        # apply "Points" schema
        prim.AddAppliedSchema("CaeAlgorithmsExternalFacesAPI")
        ns = "omni:cae:algorithms:externalFaces"
        prim.CreateRelationship(f"{ns}:dataset", custom=False).SetTargets({dataset_prim.GetPath()})
        prim.CreateRelationship(f"{ns}:colors", custom=False).SetTargets({})

        pvAPI = UsdGeom.PrimvarsAPI(primT.GetPrim())
        pvAPI.CreatePrimvar("scalar", Sdf.ValueTypeNames.FloatArray, UsdGeom.Tokens.constant).Set([0.0])

        # setup material
        material = create_material(
            "ScalarColor", stage, primT.GetPath().AppendChild("Materials").AppendChild("ScalarColor")
        )
        bind_material(primT, material)
        logger.info("created '%s''", str(prim.GetPath()))

    def undo(self):
        if self._prim_path:
            stage: Usd.Stage = get_context().get_stage()
            stage.RemovePrim(self._prim_path)
            self._prim_path = None


class CreateCaeStreamlines(omni.kit.commands.Command):
    def __init__(self, dataset_path: str, prim_path: str):
        self._dataset_path = dataset_path
        self._prim_path = prim_path

    def do(self):
        logger.info("executing %s.do()", self.__class__.__name__)
        stage: Usd.Stage = get_context().get_stage()
        dataset_prim = stage.GetPrimAtPath(self._dataset_path)
        if not dataset_prim:
            raise RuntimeError("DataSet prim is invalid!")

        width = 0.025
        primT = UsdGeom.BasisCurves.Define(stage, self._prim_path)
        primT.CreatePointsAttr().Set([(0, 0, 0), (0.1, 0, 0), (0.2, 0, 0), (0.3, 0, 0)])
        primT.CreateCurveVertexCountsAttr().Set([4])
        primT.CreateExtentAttr().Set([(0.0, 0.0, 0.0), (0.3, 0.05, 0.05)])
        primT.CreateWidthsAttr().Set([(width)])

        # primvars for the basis curve
        pvAPI = UsdGeom.PrimvarsAPI(primT.GetPrim())

        # primvars needed by shader
        pvAPI.CreatePrimvar("time", Sdf.ValueTypeNames.FloatArray, UsdGeom.Tokens.vertex).Set([0.0, 0.1, 0.2, 0.3])
        pvAPI.CreatePrimvar("rnd", Sdf.ValueTypeNames.FloatArray, UsdGeom.Tokens.uniform).Set([0.0])
        pvAPI.CreatePrimvar("scalar", Sdf.ValueTypeNames.FloatArray, UsdGeom.Tokens.vertex).Set([0.0, 0.1, 0.2, 0.3])

        primT.SetWidthsInterpolation(UsdGeom.Tokens.constant)
        primT.CreateBasisAttr().Set(UsdGeom.Tokens.bspline)
        primT.CreateTypeAttr().Set(UsdGeom.Tokens.cubic)
        primT.CreateWrapAttr().Set(UsdGeom.Tokens.pinned)

        # apply schema
        prim = primT.GetPrim()
        prim.AddAppliedSchema("CaeAlgorithmsStreamlinesAPI")
        ns = "omni:cae:algorithms:streamlines"
        prim.CreateRelationship(f"{ns}:dataset", custom=False).SetTargets({dataset_prim.GetPath()})
        prim.CreateRelationship(f"{ns}:velocity", custom=False).SetTargets({})
        prim.CreateRelationship(f"{ns}:seeds", custom=False).SetTargets({})
        prim.CreateRelationship(f"{ns}:colors", custom=False).SetTargets({})
        prim.CreateAttribute(f"{ns}:dX", Sdf.ValueTypeNames.Float, custom=False).Set(0.5)
        prim.CreateAttribute(f"{ns}:maxLength", Sdf.ValueTypeNames.Int, custom=False).Set(50)
        prim.CreateAttribute(f"{ns}:width", Sdf.ValueTypeNames.Float, custom=False).Set(width)

        # setup material
        material = create_material(
            "ScalarColor", stage, primT.GetPath().AppendChild("Materials").AppendChild("ScalarColor")
        )
        create_material(
            "AnimatedStreaks", stage, primT.GetPath().AppendChild("Materials").AppendChild("AnimatedStreaks")
        )
        bind_material(primT, material)

        logger.info("created '%s''", str(primT.GetPath()))

    def undo(self):
        if self._prim_path:
            stage: Usd.Stage = get_context().get_stage()
            stage.RemovePrim(self._prim_path)
            self._prim_path = None

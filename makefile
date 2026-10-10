# Simpler entry points for main.py.
#
#   make                         index, materials, models, pack, deploy (materials only)
#   make HITBOX_MODELS=1         same, plus infected hitbox proxy meshes
#   make CONSUMABLES=1 TRACE=1 CLEANUP=1 SOUNDS=1   same, with optional features
#   make colors                  materials, pack, deploy
#   make models ONLY=hunter HITBOX_MODELS=1   one proxy mesh
#   make verify                  check the build tree
#   make hlmv ONLY=hunter        verify and open the model viewer
#   make loose                   deploy an unpacked addon folder
#
# FORCE=1              rebuild even when inputs are unchanged
# KEEP=1               keep generated QC/SMD and studiomdl logs
# HITBOX_MODELS=1     --feat-hitbox-models
# CONSUMABLES=1        --feat-override-consumables
# TRACE=1              --feat-trace
# CLEANUP=1            --feat-cleanup
# SOUNDS=1             --feat-sounds
# MAP_RETEX=1          --feat-map-retex

PY ?= python

ONLY_FLAG :=
ifneq ($(ONLY),)
ONLY_FLAG := --only $(ONLY)
endif

FORCE_FLAG :=
ifneq ($(FORCE),)
FORCE_FLAG := --force
endif

KEEP_FLAG :=
ifneq ($(KEEP),)
KEEP_FLAG := --keep-work
endif

FEAT_FLAGS :=
ifneq ($(HITBOX_MODELS),)
FEAT_FLAGS += --feat-hitbox-models
endif
ifneq ($(CONSUMABLES),)
FEAT_FLAGS += --feat-override-consumables
endif
ifneq ($(TRACE),)
FEAT_FLAGS += --feat-trace
endif
ifneq ($(CLEANUP),)
FEAT_FLAGS += --feat-cleanup
endif
ifneq ($(SOUNDS),)
FEAT_FLAGS += --feat-sounds
endif
ifneq ($(MAP_RETEX),)
FEAT_FLAGS += --feat-map-retex
endif

.PHONY: help all index materials models pack deploy loose verify hlmv colors

# Without this, a bare `make CONSUMABLES=1 ...` builds the first target (help).
.DEFAULT_GOAL := all

help:
	@echo make            full rebuild: index, materials, models, pack, deploy
	@echo make colors     materials, pack, and deploy
	@echo make index      map models and materials to classes
	@echo make materials  flat colours (and optional feature assets)
	@echo make models     proxy meshes (requires HITBOX_MODELS=1)
	@echo make pack       write dist/cv_infected.vpk
	@echo make deploy     copy the VPK into the game addons folder
	@echo make loose      deploy an unpacked addons/cv_infected folder
	@echo make verify     check the build tree
	@echo make hlmv       verify and open a model in HLMV
	@echo.
	@echo ONLY=name        limit models or materials, and which model HLMV opens
	@echo FORCE=1          rebuild even when inputs are unchanged
	@echo KEEP=1           keep generated QC/SMD and studiomdl logs
	@echo HITBOX_MODELS=1 pack infected hitbox proxy meshes
	@echo CONSUMABLES=1    pack medkits and other pickups
	@echo TRACE=1          pack cheat-only tracers, scripts, and client cfg
	@echo CLEANUP=1        cap ragdolls/decals; C clears clutter
	@echo SOUNDS=1         install custom sounds from config.json
	@echo MAP_RETEX=1      flatten world materials from config.json

all:
	$(PY) main.py all $(ONLY_FLAG) $(FORCE_FLAG) $(KEEP_FLAG) $(FEAT_FLAGS)

index:
	$(PY) main.py index

materials:
	$(PY) main.py materials $(ONLY_FLAG) $(FORCE_FLAG) $(FEAT_FLAGS)

models:
	$(PY) main.py models $(ONLY_FLAG) $(FORCE_FLAG) $(KEEP_FLAG) $(FEAT_FLAGS)

pack:
	$(PY) main.py pack $(FEAT_FLAGS)

deploy:
	$(PY) main.py deploy $(FEAT_FLAGS)

loose:
	$(PY) main.py deploy --loose $(FEAT_FLAGS)

verify:
	$(PY) main.py verify $(ONLY_FLAG) $(FEAT_FLAGS)

hlmv:
	$(PY) main.py verify --hlmv $(ONLY_FLAG) $(FEAT_FLAGS)

colors:
	$(PY) main.py materials pack deploy $(ONLY_FLAG) $(FORCE_FLAG) $(FEAT_FLAGS)

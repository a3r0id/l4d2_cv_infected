# Simpler entry points for main.py.
#
#   make                         index, materials, models, pack, deploy
#   make colors                  materials, pack, deploy
#   make models ONLY=hunter      one proxy mesh
#   make verify                  check the build tree
#   make hlmv ONLY=hunter        verify and open the model viewer
#   make loose                   deploy an unpacked addon folder
#
# FORCE=1  rebuild even when inputs are unchanged
# KEEP=1   keep generated QC/SMD and studiomdl logs

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

.PHONY: help all index materials models pack deploy loose verify hlmv colors

help:
	@echo make            full rebuild: index, materials, models, pack, deploy
	@echo make colors     materials, pack, and deploy
	@echo make index      map models and materials to classes
	@echo make materials  flat colours and the shot-line script
	@echo make models     proxy meshes
	@echo make pack       write dist/cv_infected.vpk
	@echo make deploy     copy the VPK into the game addons folder
	@echo make loose      deploy an unpacked addons/cv_infected folder
	@echo make verify     check the build tree
	@echo make hlmv       verify and open a model in HLMV
	@echo.
	@echo ONLY=name   limit models or materials, and which model HLMV opens
	@echo FORCE=1     rebuild even when inputs are unchanged
	@echo KEEP=1      keep generated QC/SMD and studiomdl logs

all:
	$(PY) main.py all $(ONLY_FLAG) $(FORCE_FLAG) $(KEEP_FLAG)

index:
	$(PY) main.py index

materials:
	$(PY) main.py materials $(ONLY_FLAG) $(FORCE_FLAG)

models:
	$(PY) main.py models $(ONLY_FLAG) $(FORCE_FLAG) $(KEEP_FLAG)

pack:
	$(PY) main.py pack

deploy:
	$(PY) main.py deploy

loose:
	$(PY) main.py deploy --loose

verify:
	$(PY) main.py verify $(ONLY_FLAG)

hlmv:
	$(PY) main.py verify --hlmv $(ONLY_FLAG)

colors:
	$(PY) main.py materials pack deploy $(ONLY_FLAG) $(FORCE_FLAG)

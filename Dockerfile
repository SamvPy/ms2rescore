FROM ubuntu:focal

LABEL name="ms2rescore"

ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/ms2rescore

ADD pyproject.toml /ms2rescore/pyproject.toml
ADD LICENSE /ms2rescore/LICENSE
ADD README.md /ms2rescore/README.md
ADD MANIFEST.in /ms2rescore/MANIFEST.in
ADD ms2rescore /ms2rescore/ms2rescore

RUN apt-get update && apt-get install python3-pip procps -y \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install ms2rescore/

ENTRYPOINT [""]

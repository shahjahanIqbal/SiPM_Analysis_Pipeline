#usr/bin/bash

echo"Installing pipeline dependencies"
echo"Creating conda environment.."

conda env create -f environment.yml
conda activate sipm-pipeline


chmod +x bin/*.py

SCRIPTPATH = "$PWD/bin"
BASHRC = "$HOME/.bashrc"
ALIAS = sipm-pipeline = python3 "$SCRIPTPATH/wrapper.py

if ! grep -q "^export PATH =.*$SCRIPTPATH" "$BASHRC"; then
    echo "export PATH=\$PATH:$SCRIPTPATH" >>"$BASHRC"
    echo "Path added to $BASHRC"
    
else
    echo "Path already exists in $BASHRC"
fi

source "$BASHRC"

echo "Sourced"
echo " Use sipm-pipeline to run the pipeline"



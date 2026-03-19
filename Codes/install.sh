#usr/bin/bash

echo"Installing pipeline dependencies"
echo"Creating conda environment.."

conda env create -f environment.yml
conda activate sipm-pipeline

chmod +rwx *.py

mkdir ~/Vertex
cd ~/Vertex

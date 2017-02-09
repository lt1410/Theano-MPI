#!/bin/bash

#module purge
#module load theano/0.8.2 
#module unload numpy/intel/1.10.1
#module load mpi4py/openmpi/2.0.0
#module unload cuda/7.0.28
#module load pycuda/intel/2016.1.2
#module load cudnn/7.0v4.0
#module load pyzmq/intel/14.7.0

RANK=
if [ "$MV2_COMM_WORLD_RANK" != "" ]; then
    RANK=$MV2_COMM_WORLD_RANK
elif [ "$OMPI_COMM_WORLD_RANK" != "" ]; then
    RANK=$OMPI_COMM_WORLD_RANK
fi

export CUDA_DEVICE=$RANK

#if [ "$PBS_JOBTMP" != "" ]; then
#    THEANO_FLAGS="base_compiledir=$PBS_JOBTMP,$THEANO_FLAGS"
#fi

export THEANO_FLAGS="mode=FAST_RUN,device=gpu${CUDA_DEVICE},floatX=float32,$THEANO_FLAGS"

export PYTHONPATH=/scratch/lt1410/MultiGPU/Theano-MPI/lib:$PYTHONPATH

cd /scratch/lt1410/MultiGPU/Theano-MPI/run

python -u /scratch/lt1410/MultiGPU/Theano-MPI/lib/BSP_Worker.py




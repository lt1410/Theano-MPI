# Server and worker process for asynchronous parallel training
from mpi4py import MPI
from server import Server
from pprint import pprint
import time
import os

def test_intercomm(intercomm,rank):
    
    if intercomm != MPI.COMM_NULL:
        assert intercomm.remote_size == 1
        assert intercomm.size == 1
        assert intercomm.rank ==  0

        if rank == 0: # server
            message = 'from_server'
            root = MPI.ROOT
        else: # worker
            message = None
            root = 0
        message = intercomm.bcast(message, root)
        if rank == 0:
            assert message == None
        else:
            assert message == 'from_server'


class PTBase(object):
    
    '''
    Base class for Parallel Training framework
    Common routine that every device process should excute first
    
    '''
    
    def __init__(self, config, device):
        
    	self.comm = MPI.COMM_WORLD
    	self.rank = self.comm.rank
        self.size = self.comm.size
        self.config = config
        self.device = device
        
        # if self.config['worker_type'] in ['EASGD', 'ASGD']:

        # elif self.config['worker_type'] in ['avg', 'cdd']:
        self.verbose = (self.rank == 0)

        self.process_config()
        self.get_data()
        self.init_device()
        self.build_model()
        
    def process_config(self):
    
        '''
        load some config items
    
        '''
        
        # Add some items in 
        self.config['comm'] = self.comm
        self.config['rank'] = self.rank
        self.config['size'] = self.size
        #self.config['syncrule'] = self.syncrule #TODO add syncrule into config
        self.config['device'] = self.device
        
        pid = os.getpid()
        self.config['worker_id'] = pid
        self.config['sock_data'] = (self.config['sock_data'] + int(pid)) % 65535 #int(self.device[-1])
        
        self.config['verbose'] = self.verbose
        
        self.model_name=self.config['name']
        import yaml
        with open(self.model_name+'.yaml', 'r') as f:
            model_config = yaml.load(f)
        self.config = dict(self.config.items()+model_config.items())
        
        date = '-%d-%d' % (time.gmtime()[1],time.gmtime()[2])    
        import socket
        self.config['weights_dir']+= '-'+self.config['name'] \
                                     + '-'+str(self.config['size'])+'gpu-' \
                                     + str(self.config['batch_size'])+'b-' \
                                     + socket.gethostname() + date + '/'
        self.config['n_subb'] = self.config['file_batch_size']//self.config['batch_size']
                                     
        if self.rank == 0:
            if not os.path.exists(self.config['weights_dir']):
                os.makedirs(self.config['weights_dir'])
                if self.verbose: print "Creat folder: " + \
                                 self.config['weights_dir']
            else:
                if self.verbose: print "folder exists: " + \
                                 self.config['weights_dir']
            if not os.path.exists(self.config['record_dir']):
                os.makedirs(self.config['record_dir'])
                if self.verbose: print "Creat folder: " + \
                                 self.config['record_dir'] 
            else:
                if self.verbose: print "folder exists: " + \
                                 self.config['record_dir']
                                 
                                 
        # if self.config['sync_start'] and self.config['worker_type'] == 'EASGD':
#             self.config['size'] = 1
                             
        if self.verbose: pprint(self.config)
        
    def get_data(self):

        '''
        prepare filename and label list 

        '''
        from helper_funcs import unpack_configs, extend_data
        (flag_para_load, flag_top_5, train_filenames, val_filenames, \
        train_labels, val_labels, img_mean) = unpack_configs(self.config)
        
        if self.config['image_mean'] == 'RGB_mean':
            
            image_mean = img_mean.mean(axis=-1).mean(axis=-1).mean(axis=-1) 
            #c01b to # c 
            #print 'BGR_mean %s' % image_mean #[ 122.22585297  116.20915222  103.56548309]
            import numpy as np
            image_mean = image_mean[:,np.newaxis,np.newaxis,np.newaxis]

        if self.config['debug']:
            train_filenames = train_filenames[:40]
            val_filenames = val_filenames[:8]

        env_train=None
        env_val = None
            
        train_filenames,train_labels,train_lmdb_cur_list,n_train_files=\
            extend_data(self.config,train_filenames,train_labels,env_train)
        val_filenames,val_labels,val_lmdb_cur_list,n_val_files \
    		    = extend_data(self.config,val_filenames,val_labels,env_val)  
        if self.config['data_source'] == 'hkl':
            self.data = [train_filenames,train_labels,\
                        val_filenames,val_labels,img_mean] # 5 items
        else:
            raise NotImplementedError('wrong data source')
    
        if self.verbose: print 'train on %d files' % n_train_files  
        if self.verbose: print 'val on %d files' % n_val_files
    
    def init_device(self):
    
        gpuid = int(self.device[-1])

        # pycuda and zmq set up
        import pycuda.driver as drv

        drv.init()
        dev = drv.Device(gpuid)
        ctx = dev.make_context()
        
        self.drv = drv
        self.dev = dev
        self.ctx = ctx
    
        import theano.sandbox.cuda
        theano.sandbox.cuda.use(self.config['device'])
        
    def build_model(self):

        import theano
        theano.config.on_unused_input = 'warn'

        if self.model_name=='googlenet':
        	from models.googlenet import GoogLeNet
        	self.model = GoogLeNet(self.config)

        elif self.model_name=='alexnet':
        	from models.alex_net import AlexNet
        	self.model = AlexNet(self.config)
            
        elif self.model_name=='vggnet':
            
            if self.config['pretrain']:
                from models.vggnet_11_shallow import VGGNet_11 as VGGNet
            else:
                if self.config['source'] == 'lasagne':
                    from models.lasagne_model_zoo.vgg import VGG as VGGNet
                elif self.config['source'] == 'Theano-MPI':
                    from models.vggnet_16 import VGGNet_16 as VGGNet
                else:
                    raise NotImplementedError
                
            self.model = VGGNet(self.config)
            
        elif self.model_name=='customized':
            from models.customized import Customized
            self.model = Customized(self.config)
            
        else:
            raise NotImplementedError("wrong model name")
            
        self.model.img_mean = self.data[4]
        
        
class PTServer(Server, PTBase):
    '''
    Genearl Server class in Parallel Training framework
    Manage MPI connection requests from workers
    '''
    
    def __init__(self, port, config, device):
        Server.__init__(self,port=port)
        PTBase.__init__(self,config=config,device=device)
        
        #######
        
        self.info = MPI.INFO_NULL

        self.port = MPI.Open_port(self.info)
        
        self.service = 'parallel-training'
        
        MPI.Publish_name(self.service, self.info, self.port)
        
        self.worker_comm = {}
        self.worker_rank = {}
        self.first_worker_id = None
    
    def close():
        
        MPI.Unpublish_name(self.service, self.info, self.port)
        print '[Server] Service unpublished'

        MPI.Close_port(self.port)
        print '[Server] Service port closed'
        
    def process_request(self, worker_id, message):

        # override Server class method, for connection related request
        reply = None
        
        if message in ['connect','sync_register']:
            if self.first_worker_id == None:
                self.first_worker_id = worker_id
                print '[Server] recording worker is %s' % worker_id
                reply = 'first'
        
        return reply
        
    def action_after(self, worker_id, message):
        
        # override Server class method, for connection related action
        
        if message == 'connect': # Connecting asynchronously started workers
            
            intercomm = MPI.COMM_WORLD.Accept(self.port, self.info, root=0)
            
            self.worker_comm[str(worker_id)] = intercomm #TODO BUG there's a small chance that worker processes started on different node have the same pid
            self.worker_rank[str(worker_id)] = 0 # remote size = 1, remote rank=0
            
            test_intercomm(intercomm, rank=0)
                             
            print '[Server] connected to worker', worker_id
            
        if 'sync_register' in message: # Connecting synchronously started workers
            
            self.worker_comm[str(worker_id)] = self.comm
            
            worker_rank = self.comm.recv(source = MPI.ANY_SOURCE, tag=int(worker_id))
            
            self.worker_rank[str(worker_id)] = int(worker_rank)
            
            print '[Server] registered worker', worker_id
            
        elif message == 'disconnect':
            
            intercomm = self.worker_comm[str(worker_id)]
            try:
                intercomm.Disconnect()
            except:
                pass
            self.worker_comm.pop(str(worker_id))
            
            print '[Server] disconnected with worker', worker_id
            
            if bool(self.worker_comm) == False:
                # empty dict
                self.ctx.pop()
                exit(0)
            
    
class PTWorker(PTBase):
    
    '''
    General Worker class in Parallel Training framework
    Start parallel loading process if needed
    
    '''
    
    def __init__(self, config, device):
        PTBase.__init__(self, config = config, device = device)


    def prepare_para_load(self):
        
        if self.config['para_load']:
            self.spawn_load()
            self.para_load_init()
        
           
    def spawn_load(self):
        
        'parallel loading process'
    
        num_spawn = 1
        hostname = MPI.Get_processor_name()
        mpiinfo = MPI.Info.Create()
        mpiinfo.Set(key = 'host',value = hostname)
        ninfo = mpiinfo.Get_nkeys()
        if self.verbose: print ninfo
        import sys
        mpicommand = sys.executable

        gpuid = self.device[-1] #str(os.environ['OMPI_COMM_WORLD_LOCAL_RANK'])
        if self.verbose: print gpuid
        socketnum = 0
        
        # adjust numactl according to the layout of copper nodes [1-8]
        if int(gpuid) > 3:
            socketnum=1 
        printstr = "rank" + str(self.rank) +":numa"+ str(socketnum)
        if self.verbose: print printstr

        # spawn loading process
        # self.icomm= MPI.COMM_SELF.Spawn('numactl', \
        #         args=['-N',str(socketnum),mpicommand,\
        #                         '../lib/base/proc_load_mpi.py',gpuid],\
        
        file_dir = os.path.dirname(os.path.realpath(__file__)) # get the dir of PT.py
        
        self.icomm= MPI.COMM_SELF.Spawn(mpicommand, \
                args=[file_dir+'/proc_load_mpi.py', gpuid],\
                info = mpiinfo, maxprocs = num_spawn)
        self.config['icomm'] = self.icomm
                
    def para_load_init(self):
        
        # 0. send config dict (can't carry any special objects) to loading process
        
        self.icomm.isend(self.config,dest=0,tag=99)
    	
        drv = self.drv
        shared_x = self.model.shared_x
        img_mean = self.data[4]

        sock_data = self.config['sock_data']
        
        import zmq
        sock = zmq.Context().socket(zmq.PAIR)
        sock.connect('tcp://localhost:{0}'.format(sock_data))
        
        #import theano.sandbox.cuda
        #theano.sandbox.cuda.use(config.device)
        import theano.misc.pycuda_init
        import theano.misc.pycuda_utils
        # pass ipc handle and related information
        gpuarray_batch = theano.misc.pycuda_utils.to_gpuarray(
            shared_x.container.value)
        h = drv.mem_get_ipc_handle(gpuarray_batch.ptr)
        # 1. send ipc handle of shared_x
        sock.send_pyobj((gpuarray_batch.shape, gpuarray_batch.dtype, h))

        # 2. send img_mean
        self.icomm.send(img_mean, dest=0, tag=66)
    
    def para_load_close(self):
        
        # send an stop mode
        self.icomm.send('stop',dest=0,tag=40) # TODO use this only when loading process is ready to receive mode
        self.icomm.send('stop',dest=0,tag=40)
        self.icomm.Disconnect()
        self.ctx.detach()
        
        
    def prepare_train_fn(self):
        
        # to be defined in different type of PTWorkers child class
        
        # to make sure model compiles correct updating function and allocate necessary extra param memory that correspond to the selected parallel worker type and parallel update type
        
        raise NotImplementedError('Need to redefine this function in a child class of PTWorker')
        
      
    def run(self):
        
        # to be defined in child class
        
        pass
        


        

if __name__ == '__main__':
    
    with open('config.yaml', 'r') as f:
        config = yaml.load(f)
        
    #device = 'gpu' + str(os.environ['OMPI_COMM_WORLD_LOCAL_RANK'])
        
    server = PTServer(port=5555, config=config, device='gpu7')
    
    server.run()
        
    
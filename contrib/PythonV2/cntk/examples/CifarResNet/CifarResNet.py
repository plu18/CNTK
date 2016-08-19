import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
import cntk.cntk_py as cntk_py
from cntk.ops import variable, constant, parameter, cross_entropy_with_softmax, combine, classification_error, plus, times, relu, convolution, batch_normalization, pooling,AVG_POOLING
from cntk.utils import create_minibatch_source, cntk_device

def create_mb_source():    
    image_height = 32
    image_width = 32
    num_channels = 3
    num_classes = 10
    map_file = r"../../../../../Examples/Image/Miscellaneous/CIFAR-10/cifar-10-batches-py/train_map.txt"
    mean_file = r"../../../../../Examples/Image/Miscellaneous/CIFAR-10/cifar-10-batches-py/CIFAR-10_mean.xml"

    crop_transform_config = dict()
    crop_transform_config["type"] = "Crop"
    crop_transform_config["cropType"] = "Random"
    crop_transform_config["cropRatio"] = "0.8"
    crop_transform_config["jitterType"] = "uniRatio"

    scale_transform_config = dict()
    scale_transform_config["type"] = "Scale"
    scale_transform_config["width"] = image_width
    scale_transform_config["height"] = image_height
    scale_transform_config["channels"] = num_channels
    scale_transform_config["interpolations"] = "linear"

    mean_transform_config = dict()
    mean_transform_config["type"] = "Mean"
    mean_transform_config["meanFile"] = mean_file

    all_transforms = [ crop_transform_config, scale_transform_config, mean_transform_config ]

    features_stream_config = dict()
    features_stream_config["transforms"] = all_transforms

    labels_stream_config = dict()
    labels_stream_config["labelDim"] = num_classes

    input_streams_config = dict()
    input_streams_config["features"] = features_stream_config
    input_streams_config["labels"] = labels_stream_config

    deserializer_config = dict()
    deserializer_config["type"] = "ImageDeserializer"
    deserializer_config["module"] = "ImageReader"
    deserializer_config["file"] = map_file
    deserializer_config["input"] = input_streams_config

    minibatch_config = dict()
    minibatch_config["epochSize"] = epoch_size
    minibatch_config["deserializers"] = [deserializer_config]

    return create_minibatch_source(minibatch_config)    

def conv_bn_layer(input, out_feature_map_count, kernel_width, kernel_height, h_stride, v_stride, w_scale, b_value, sc_value, bn_time_const, device):
    num_in_channels = input.shape().dimensions()[0]        
    #TODO: use RandomNormal to initialize, needs to be exposed in the python api
    conv_params = parameter(shape=(num_in_channels, kernel_height, kernel_width, out_feature_map_count), device_id=device)       
    conv_func = convolution(conv_params, input, (num_in_channels, v_stride, h_stride))    
    #TODO: initialize using b_value and sc_value, needs to be exposed in the python api
    bias_params = parameter(shape=(out_feature_map_count,), device_id=device)   
    scale_params = parameter(shape=(out_feature_map_count,), device_id=device)   
    running_mean = constant((out_feature_map_count,), 0.0, device_id=device)
    running_invstd = constant((out_feature_map_count,), 0.0, device_id=device)
    return batch_normalization(conv_func.output(), scale_params, bias_params, running_mean, running_invstd, True, bn_time_const, 0.0, 0.000000001)    

def conv_bn_relu_layer(input, out_feature_map_count, kernel_width, kernel_height, h_stride, v_stride, w_scale, b_value, sc_value, bn_time_const, device):
    conv_bn_function = conv_bn_layer(input, out_feature_map_count, kernel_width, kernel_height, h_stride, v_stride, w_scale, b_value, sc_value, bn_time_const, device)
    return relu(conv_bn_function.output())

def resnet_classifer(input, num_classes, device, output_name):
    #TOTO: add all missing layers
    conv_w_scale = 7.07
    conv_b_value = 0

    fc1_w_scale = 0.4
    fc1_b_value = 0

    sc_value = 1
    bn_time_const = 4096

    kernel_width = 3
    kernel_height = 3

    conv1_w_scale = 0.26
    c_map1 = 16    
    
    conv1 = conv_bn_relu_layer(input, c_map1, kernel_width, kernel_height, 1, 1, conv1_w_scale, conv_b_value, sc_value, bn_time_const, device)
    
    c_map2 = 32
    
    c_map3 = 64

    # Global average pooling
    #TODO: use original values
    poolw = 32
    poolh = 32
    poolh_stride = 1
    poolv_stride = 1

    pool = pooling(conv1.output(), AVG_POOLING, (1, poolh, poolw), (1, poolv_stride, poolh_stride))
    out_times_params = parameter(shape=(c_map1, 1, 1, num_classes), device_id=device)
    out_bias_params = parameter(shape=(num_classes,), device_id=device)
    t = times(pool.output(), out_times_params)
    return plus(t.output(), out_bias_params, output_name)    

if __name__=='__main__':      
    dev = 0
    cntk_dev = cntk_device(dev)
    epoch_size = sys.maxsize    
    mbs = create_mb_source()    
    stream_infos = mbs.stream_infos()      
    for si in stream_infos:
        if si.m_name == 'features':
            features_si = si
        elif si.m_name == 'labels':
            labels_si = si

    image_shape = features_si.m_sample_layout.dimensions()          
    image_shape = (image_shape[2], image_shape[0], image_shape[1])
    
    num_classes = labels_si.m_sample_layout.dimensions()[0]
    
    image_input = variable(image_shape, features_si.m_element_type, needs_gradient=False, name="Images")    
    classifer_output = resnet_classifer(image_input, num_classes, dev, "classifierOutput")
    label_var = variable((num_classes,), features_si.m_element_type, needs_gradient=False, name="Labels")
    
    ce = cross_entropy_with_softmax(classifer_output.output(), label_var)
    pe = classification_error(classifer_output.output(), label_var)
    image_classifier = combine([ce, pe, classifer_output], "ImageClassifier")

    learning_rate_per_sample = 0.0078125
    trainer = cntk_py.Trainer(image_classifier, ce.output(), [cntk_py.sgdlearner(image_classifier.parameters(), learning_rate_per_sample)])
    
    mb_size = 32
    num_mbs = 100

    minibatch_size_limits = dict()    
    minibatch_size_limits[features_si] = (0,mb_size)
    minibatch_size_limits[labels_si] = (0, mb_size)
    for i in range(0,num_mbs):    
        mb=mbs.get_next_minibatch(minibatch_size_limits, cntk_dev)
        
        arguments = dict()
        arguments[image_input] = mb[features_si].m_data
        arguments[label_var] = mb[labels_si].m_data
        
        trainer.train_minibatch(arguments, cntk_dev)

        freq = 20
        if i % freq == 0:
            #TODO: read loss values from GPU
            #print(str(i+freq) + ": " + str(trainer.previous_minibatch_training_loss_value().data().to_numpy()))
            print (i)

    

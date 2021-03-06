import sys, os, os.path, glob, io, base64
import cntk as C
import numpy, random, string

keras_backend = 'cntk'
os.environ['KERAS_BACKEND'] = keras_backend

try:
    from azureml.datacollector import ModelDataCollector
except ImportError:
    print("Data collection is currently only supported in docker mode. May be disabled for local mode.")
    # Mocking out model data collector functionality
    class ModelDataCollector(object):
        def nop(*args, **kw): pass
        def __getattr__(self, _): return self.nop
        def __init__(self, *args, **kw): return None
    pass

def generate_labels(labels_folder, labels_filename):
    """Save labels file
    
    In order to build labels file, folder names inside labels_folder are retrieved, and saved as a json array
    
    Arguments:
        labels_folder {string} -- Images folder
        labels_filename {string} -- Labels filename
    """
    import os, json
    
    if not os.path.exists(labels_filename):
        labels = [ item for item in os.listdir(labels_folder) if os.path.isdir(os.path.join(labels_folder, item)) ]
        numpy.savetxt(labels_filename, [json.dumps(labels)], fmt='%s')

def pilImgToBase64(pilImg):
    """Encodes PIL image to base64
    
    Arguments:
        pilImg {PIL} -- PIL image
    
    Returns:
        string -- Encoded base64 image string        
    """
    pilImg = pilImg.convert('RGB')
    imgio = io.BytesIO()
    pilImg.save(imgio, 'PNG')
    imgio.seek(0)
    dataimg = base64.b64encode(imgio.read())
    return dataimg.decode('utf-8')

def base64ToPilImg(base64ImgString):
    """Converts a base64 encoded image to PIL image 

    Arguments:
        base64ImgString {string} -- Encoded base64 image string

    Returns:
        PIL -- PIL image
    """
    from PIL import Image
    if base64ImgString.startswith('b\''):
        base64ImgString = base64ImgString[2:-1]
    base64Img   =  base64ImgString.encode('utf-8')
    decoded_img = base64.b64decode(base64Img)
    img_buffer  = io.BytesIO(decoded_img)
    pil_img = Image.open(img_buffer).convert('RGB')
    return pil_img

def load_cntk(model_file):
    """Load model from file
    
    Arguments:
        model_file {string} -- File path name classification model
    
    Returns:
        model -- classification model
    """
    
    cntk_model = C.load_model(model_file)
    return cntk_model

def rgb_norm(val):
    """Pixel normalization

    Function equivalent to keras.application.inception_v3.preprocess_input

    Arguments:
        val {int} -- Pixel value (0:255 range)

    Returns:
        int -- Pixel normalized value (-1:1 range)
    """
    return 2/255*(val-255)+1

def load_image(img_file, IM_WIDTH=224, IM_HEIGHT=224):
    """Load image into numpy array

    Load image into numpy array, resizing to IM_WIDTH and IM_HEIGHT dimensions, 
    and applying pixel normalization
    
    Arguments:
        img_file {string} -- File path image
    
    Keyword Arguments:
        IM_WIDTH {int} -- Resized image width (default: {224})
        IM_HEIGHT {int} -- Resized image height (default: {224})
    
    Returns:
        int[] -- numpy array image
    """    
    from keras.preprocessing import image

    # load image into numpy array, resizing if needed
    img = image.load_img(img_file, target_size=(IM_WIDTH, IM_HEIGHT))
    x = image.img_to_array(img)
    x = numpy.expand_dims(x, axis=0)

    x = rgb_norm(x)

    return x

# Prepare the web service definition by authoring
# init() and run() functions. Test the functions
# before deploying the web service.
def init():
    """Web Service Initialization
    
        Prepare the web service definition by authoring
        init() and run() functions. Test the functions
        before deploying the web service.
    """
    import json
    global inputs_dc, prediction_dc
    global model, labels

    model = load_cntk('model_cntk.pb')
    labels = json.load(open('labels.json'))

    inputs_dc = ModelDataCollector("model_tf.pb", identifier="inputs")
    prediction_dc = ModelDataCollector("model_tf.pb", identifier="prediction")

def run(input_df):
    """Executes prediction
    
    Arguments:
        input_df {string} -- base64 enconded image
    
    Returns:
        string -- json parsed classification output (label/probability array)
    """    
    import pandas

    # Generates random image name
    uploadedImage = ''.join([random.choice(string.ascii_letters + string.digits) for n in range(16)]) + ".jpg"
    
    inputs_dc.collect(str(input_df))
    
    # Save file to disk and load (applying keras image transformations as applied in training)
    pil_img = base64ToPilImg(input_df["base64image"])
    pil_img.save(uploadedImage, "JPEG")    
    image = load_image(uploadedImage)

    # Classification
    pred = model.eval(image)
    prediction_dc.collect(pred)

    os.remove(uploadedImage)

    # Format json output classification
    df = {'probability':pred[0], 'label': labels}
    df = pandas.DataFrame(df)    

    json_pred = df.to_json(orient='records')
    print("result:", json_pred)
    return json_pred

def main():
    """WebService unit test and swagger schema generation
    """
    from azureml.api.schema.dataTypes import DataTypes
    from azureml.api.schema.sampleDefinition import SampleDefinition
    from azureml.api.realtime.services import generate_schema
    from PIL import Image
    import json, os

    # Save labels
    generate_labels("data/train", "labels.json")
    print("Labels generated")

    # Create random image
    pilImg = Image.fromarray((numpy.random.rand(224, 224, 3) * 255).astype('uint8')) #random 224x224 pixels image
    base64ImgString = pilImgToBase64(pilImg)  

    df = { 'base64image' : base64ImgString }

    # Turn on data collection debug mode to view output in stdout
    os.environ["AML_MODEL_DC_DEBUG"] = 'true'

    # Test the output of the classification
    init()
    run(df)

    inputs = {"input_df": SampleDefinition(DataTypes.STANDARD, df)}

    #Genereate the schema
    generate_schema(run_func=run, inputs=inputs, filepath='./outputs/service_schema.json')
    print("Schema generated")

if __name__ == '__main__':
    main()

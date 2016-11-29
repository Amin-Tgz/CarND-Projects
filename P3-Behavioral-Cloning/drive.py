import argparse
import base64
import json

import numpy as np
import socketio
import eventlet
import eventlet.wsgi
import time
from PIL import Image
from PIL import ImageOps
from flask import Flask, render_template
from io import BytesIO

from keras.models import model_from_json
from keras.preprocessing.image import ImageDataGenerator, array_to_img, img_to_array

import tensorflow as tf
from tensorflow.python.ops import control_flow_ops
tf.python.control_flow_ops = control_flow_ops


sio = socketio.Server()
app = Flask(__name__)
model = None
prev_image_array = None

from keras.applications.vgg16 import preprocess_input
vgg = False

def normalize_color(image_data):
    a = -0.5
    b = +0.5

    Xmin = 0.0
    Xmax = 255.0

    norm_img = np.empty_like(image_data, dtype=np.float32)

    norm_img = a + (image_data - Xmin)*(b-a)/(Xmax - Xmin)
    return norm_img

@sio.on('telemetry')
def telemetry(sid, data):
    # The current steering angle of the car
    steering_angle = data["steering_angle"]
    # The current throttle of the car
    throttle = data["throttle"]
    # The current speed of the car
    speed = data["speed"]
    # The current image from the center camera of the car
    imgString = data["image"]
    image = Image.open(BytesIO(base64.b64decode(imgString)))

    if vgg:
        x = np.asarray(image.resize((224, 224)), dtype=np.float32)
        x = np.expand_dims(x, axis=0)
        transformed_image_array = preprocess_input(x)
    else:
        image = image.convert('YCbCr')
        image_array = np.asarray(image, dtype=np.float32)
        # transformed_image_array = (image_array[None, :, :, :])/255. # model <= 2
        transformed_image_array = normalize_color(image_array[None, :, :, :]) # model >= 3

    # This model currently assumes that the features of the model are just the images. Feel free to change this.
    steering_angle = float(model.predict(transformed_image_array, batch_size=1))

    steering_angle = steering_angle*2 - 1.  # -- for model >= 4
    # The driving model currently just outputs a constant throttle. Feel free to edit this.

    # Throttle down at higher angles
    # neg throttle if |Steering| > 3.75 deg
    speed = float(speed)
    throttle_max = 0.1  # like spring constant
    throttle_min = -0.2
    steering_max = 2./25.
    top_speed = 10  # Drove with 15, a little unstable

    if speed > (1.0 - abs(steering_angle))*top_speed:
        throttle = abs(steering_angle)/steering_max * throttle_min
        throttle = max(throttle_min, throttle)
    if speed < 5:
        throttle = throttle_max

    print(steering_angle, throttle)
    send_control(steering_angle, throttle)


@sio.on('connect')
def connect(sid, environ):
    print("connect ", sid)
    send_control(0, 0)


def send_control(steering_angle, throttle):
    sio.emit("steer", data={
    'steering_angle': steering_angle.__str__(),
    'throttle': throttle.__str__()
    }, skip_sid=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Remote Driving')
    parser.add_argument('model', type=str,
    help='Path to model definition json. Model weights should be on the same path.')
    args = parser.parse_args()
    with open(args.model, 'r') as jfile:
        # model = model_from_json(json.load(jfile))
        model = model_from_json(jfile.read())

    model.compile("adam", "mse")
    weights_file = args.model.replace('json', 'h5')
    model.load_weights(weights_file)

    # wrap Flask application with engineio's middleware
    app = socketio.Middleware(sio, app)

    # deploy as an eventlet WSGI server
    eventlet.wsgi.server(eventlet.listen(('', 4567)), app)

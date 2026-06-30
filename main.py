from fastapi import FastAPI
from fastapi.params import Body
from pydantic import BaseModel, Field
from random import randrange
from typing import Optional
app = FastAPI()
  
class Post(BaseModel):
    title : str
    content : str
    rating: Optional[int] = None    

my_post=[{"title": "title of the post 1", "content" : "content of the post 1", "id":1}]

@app.get("/posts")
def get_posts():
    return{"data":my_post}

@app.post("/posts")
def create_posts(new_post:Post):
    post_dict = new_post.model_dump()
    post_dict['id'] = randrange(0,100000)
    my_post.append(post_dict)
    return{"data":post_dict}

@app.get("get/latest")